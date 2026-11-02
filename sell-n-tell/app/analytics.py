"""BigQuery Agent Analytics Plugin helpers and lifecycle management (AIML-2823).

This module provides factory and pre-warming/shutdown lifecycle functions for ADK's
BigQueryAgentAnalyticsPlugin, keeping main.py clean and allowing test execution
without importing the agent or requiring live GCP credentials.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.cloud import bigquery

logger = logging.getLogger(__name__)


_ANALYTICS_STATUS: dict[str, Any] = {
    "configured": False,
    "enabled": False,
    "prewarmed": False,
    "error_code": None,
    "table_id": None,  # internal diagnostic only, not exposed on unauthenticated /healthz
    "error": None,     # internal diagnostic only, not exposed on unauthenticated /healthz
}


def get_analytics_status() -> dict[str, Any]:
    """Return public health/readiness status of BigQuery analytics plugin.

    Exposes only booleans and high-level error codes to prevent leaking
    internal GCP infrastructure identifiers (such as project IDs, dataset IDs,
    table names, or internal exception traces) via unauthenticated health probes.
    """
    return {
        "configured": bool(_ANALYTICS_STATUS["configured"]),
        "enabled": bool(_ANALYTICS_STATUS["enabled"]),
        "prewarmed": bool(_ANALYTICS_STATUS["prewarmed"]),
        "error_code": _ANALYTICS_STATUS["error_code"],
    }


def build_bigquery_analytics_plugin(
    project_id: str | None,
    dataset_id: str | None,
    table_id: str = "agent_events",
    location: str = "US",
    credentials: Any = None,
) -> BigQueryAgentAnalyticsPlugin | None:
    """Factory to construct BigQueryAgentAnalyticsPlugin with pre-warmed creds and create_views=False.

    AIML-2823:
    1. Requires explicit project_id and dataset_id (no silent code-level fallback to PoC).
    2. Uses pre-warmed credentials to bypass off-GCP metadata server timeouts.
       Note: start_background_refresh swaps credentials on live_client each cycle,
       while the BigQuery plugin retains this initial credential object and relies on
       google-auth's built-in on-demand refresh.
    3. create_views=False prevents running 20+ sequential CREATE OR REPLACE VIEW DDL queries.
    """
    if not project_id:
        logger.warning(
            "GOOGLE_CLOUD_PROJECT not set -- BigQuery audit logging disabled."
        )
        _ANALYTICS_STATUS["configured"] = False
        _ANALYTICS_STATUS["enabled"] = False
        _ANALYTICS_STATUS["error_code"] = "MISSING_PROJECT"
        _ANALYTICS_STATUS["error"] = "GOOGLE_CLOUD_PROJECT not set"
        return None

    if not dataset_id:
        logger.warning(
            "BQ_ANALYTICS_DATASET_ID is not set in environment -- BigQuery audit logging disabled "
            "(set BQ_ANALYTICS_DATASET_ID to enable; default is not hardcoded to prevent accidental PoC writes)."
        )
        _ANALYTICS_STATUS["configured"] = False
        _ANALYTICS_STATUS["enabled"] = False
        _ANALYTICS_STATUS["error_code"] = "MISSING_DATASET"
        _ANALYTICS_STATUS["error"] = "BQ_ANALYTICS_DATASET_ID not set"
        return None

    if credentials is None:
        logger.warning(
            "Pre-warmed live_client credentials not found; BigQuery plugin will fall back "
            "to google.auth.default(), which may incur metadata server latency in non-GCP environments."
        )

    try:
        plugin = BigQueryAgentAnalyticsPlugin(
            project_id=project_id,
            dataset_id=dataset_id,
            table_id=table_id,
            location=location,
            credentials=credentials,
            config=BigQueryLoggerConfig(
                event_allowlist=None,
                create_views=False,
            ),
        )
        logger.info(
            "BigQueryAgentAnalyticsPlugin initialized (project=%s, dataset=%s, table=%s).",
            project_id,
            dataset_id,
            table_id,
        )
        _ANALYTICS_STATUS["configured"] = True
        _ANALYTICS_STATUS["enabled"] = True
        _ANALYTICS_STATUS["error_code"] = None
        _ANALYTICS_STATUS["table_id"] = f"{project_id}.{dataset_id}.{table_id}"
        _ANALYTICS_STATUS["error"] = None
        return plugin
    except Exception as e:  # noqa: BLE001 - audit logging must never block startup
        logger.exception(
            "Failed to initialize BigQueryAgentAnalyticsPlugin (project=%s, dataset=%s); "
            "continuing without audit logging.",
            project_id,
            dataset_id,
        )
        _ANALYTICS_STATUS["configured"] = False
        _ANALYTICS_STATUS["enabled"] = False
        _ANALYTICS_STATUS["error_code"] = "INIT_FAILED"
        _ANALYTICS_STATUS["error"] = str(e)
        return None


async def prewarm_analytics_plugins(plugins: list[Any], timeout: float = 10.0) -> None:
    """Pre-warm analytics plugins off the request path at server startup (AIML-2823).

    In ADK 2.10.0, BigQueryAgentAnalyticsPlugin._ensure_started() handles initialization
    and returns a structured outcome ('ok', 'disabled', 'failed', 'aborted').
    When config.enabled is False, it immediately returns 'disabled' with zero side effects.
    When initialization encounters table/dataset errors, it raises/records the failure and
    _started remains False.

    This function:
    1. Awaits _ensure_started() bounded by a timeout.
    2. Defense-in-depth: explicitly verifies table existence/access via client.get_table()
       bounded by a deadline and timeout if _started is True.
    3. If pre-warming fails, times out, or table verification fails, logs at ERROR level,
       records high-level error_code in _ANALYTICS_STATUS, and sets p.config.enabled = False
       (which short-circuits _log_event without stalling live turns).
    """
    for p in plugins:
        if not hasattr(p, "_ensure_started"):
            continue
        try:
            logger.info("Pre-warming BigQuery analytics plugin at server startup...")
            await asyncio.wait_for(p._ensure_started(), timeout=timeout)
            if getattr(p, "_started", False):
                # Defense-in-depth: verify that the table exists and is accessible.
                # While ADK 2.10.0 raises on table/dataset errors during _ensure_started,
                # verifying get_table confirms end-to-end table accessibility before live turns.
                if (
                    hasattr(p, "client")
                    and p.client is not None
                    and hasattr(p, "full_table_id")
                ):
                    try:
                        loop = asyncio.get_running_loop()
                        retry_policy = bigquery.DEFAULT_RETRY.with_deadline(timeout)
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                functools.partial(
                                    p.client.get_table,
                                    p.full_table_id,
                                    retry=retry_policy,
                                    timeout=timeout,
                                ),
                            ),
                            timeout=timeout,
                        )
                    except Exception as e:
                        logger.error(
                            "BigQuery analytics table verification failed for table '%s': %s; disabling plugin.",
                            getattr(p, "full_table_id", ""),
                            e,
                        )
                        _ANALYTICS_STATUS["enabled"] = False
                        _ANALYTICS_STATUS["prewarmed"] = False
                        _ANALYTICS_STATUS["error_code"] = "TABLE_CHECK_FAILED"
                        _ANALYTICS_STATUS["error"] = str(e)
                        if getattr(p, "config", None) is not None:
                            p.config.enabled = False
                        continue

                logger.info(
                    "BigQuery analytics plugin pre-warmed successfully (table=%s).",
                    getattr(p, "full_table_id", ""),
                )
                _ANALYTICS_STATUS["enabled"] = True
                _ANALYTICS_STATUS["prewarmed"] = True
                _ANALYTICS_STATUS["error_code"] = None
                _ANALYTICS_STATUS["error"] = None
            else:
                err = getattr(p, "_startup_error", "Unknown startup error")
                logger.error(
                    "BigQuery analytics plugin pre-warming failed: %s; disabling plugin.",
                    err,
                )
                _ANALYTICS_STATUS["enabled"] = False
                _ANALYTICS_STATUS["prewarmed"] = False
                _ANALYTICS_STATUS["error_code"] = "PREWARM_FAILED"
                _ANALYTICS_STATUS["error"] = str(err)
                if getattr(p, "config", None) is not None:
                    p.config.enabled = False
        except asyncio.TimeoutError:
            logger.error(
                "BigQuery analytics plugin pre-warming timed out after %.1fs; disabling plugin.",
                timeout,
            )
            _ANALYTICS_STATUS["enabled"] = False
            _ANALYTICS_STATUS["prewarmed"] = False
            _ANALYTICS_STATUS["error_code"] = "PREWARM_TIMEOUT"
            _ANALYTICS_STATUS["error"] = f"Pre-warming timed out after {timeout:.1f}s"
            if getattr(p, "config", None) is not None:
                p.config.enabled = False
        except Exception as e:
            logger.error(
                "BigQuery analytics plugin pre-warming failed: %s; disabling plugin.",
                e,
            )
            _ANALYTICS_STATUS["enabled"] = False
            _ANALYTICS_STATUS["prewarmed"] = False
            _ANALYTICS_STATUS["error_code"] = "PREWARM_FAILED"
            _ANALYTICS_STATUS["error"] = str(e)
            if getattr(p, "config", None) is not None:
                p.config.enabled = False


async def shutdown_analytics_plugins(plugins: list[Any], timeout: float = 3.0) -> None:
    """Flush pending BigQuery audit logs on shutdown (AIML-2823).

    Bounded by timeout (default 3.0s) so a stalled BigQuery flush does not exhaust
    Cloud Run's SIGTERM termination grace period before session state persistence finishes.
    """
    for p in plugins:
        if hasattr(p, "shutdown"):
            try:
                logger.info("Flushing BigQuery analytics plugin queue on shutdown...")
                await asyncio.wait_for(p.shutdown(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out flushing BigQuery analytics plugin queue after %.1fs on shutdown",
                    timeout,
                )
            except Exception as e:
                logger.warning("Error shutting down BigQuery analytics plugin: %s", e)
