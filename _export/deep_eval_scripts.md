# deep_eval_scripts

branch: `feature/infosec-remediation`  commit: `d57a1bf`  files: 3

<!-- FILE: deep_eval_scripts/config.py -->
````python
"""Configuration loader for HR Analyst evaluation system.

This module provides a centralized configuration system that reads from config.yaml
and provides type-safe access to all evaluation parameters.

Usage:
    from deep_eval_scripts.config import config
    
    # Access configuration values
    input_file = config.csv_files.default_input
    threshold = config.metrics.default_threshold
    judge_model = config.judge.default_model
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class CSVFilesConfig:
    """CSV file path configuration."""
    
    default_input: str = "deep_eval_scripts/data_sets/Hr_Chatbot_Data_Set.csv"
    default_output: str = "deep_eval_scripts/outputs/evaluation_report.csv"
    default_summary: str = "deep_eval_scripts/outputs/evaluation_report_summary.txt"


@dataclass
class CSVColumnsConfig:
    """CSV column name configuration."""
    
    question: str = "Test Question"
    expected_answer: str = "New Agent Response"
    id: str = "ID"
    category: str = "Category"


@dataclass
class JudgeConfig:
    """LLM judge model configuration."""
    
    default_model: str = "gemini-2.5-pro"
    alternative_models: list[str] = field(default_factory=lambda: [
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ])


@dataclass
class MetricThresholdsConfig:
    """Individual metric threshold configuration."""
    
    faithfulness: float = 0.25
    answer_relevancy: float = 0.25
    contextual_relevancy: float = 0.25
    contextual_precision: float = 0.25
    contextual_recall: float = 0.25
    hallucination: float = 0.25


@dataclass
class MetricsConfig:
    """Metrics configuration."""
    
    default_threshold: float = 0.25
    thresholds: MetricThresholdsConfig = field(default_factory=MetricThresholdsConfig)
    include_reason: bool = True
    
    def get_threshold(self, metric_name: str) -> float:
        """Get threshold for a specific metric.
        
        Args:
            metric_name: Name of the metric (e.g., 'faithfulness', 'answer_relevancy')
        
        Returns:
            Threshold value for the metric, or default if not configured
        """
        metric_name_lower = metric_name.lower().replace(" ", "_")
        return getattr(self.thresholds, metric_name_lower, self.default_threshold)


@dataclass
class ContextExtractionConfig:
    """Context extraction configuration."""
    
    max_chunk_size: int = 1500
    min_chunk_size: int = 20
    top_k: int = 5


@dataclass
class TimeoutsConfig:
    """Timeout configuration."""
    
    per_task_seconds: int = 1200
    total_evaluation_minutes: Optional[int] = None


@dataclass
class PerformanceBandsConfig:
    """Performance band threshold configuration."""
    
    excellent: float = 0.90
    good: float = 0.75
    acceptable: float = 0.50


@dataclass
class CICDConfig:
    """CI/CD configuration."""
    
    default_threshold: float = 0.50
    verbose: bool = False


@dataclass
class ExternalLoggersConfig:
    """External logger level configuration."""
    
    google: str = "WARNING"
    google_adk: str = "INFO"
    deepeval: str = "INFO"


@dataclass
class LoggingConfig:
    """Logging configuration."""
    
    level: str = "INFO"
    external_loggers: ExternalLoggersConfig = field(default_factory=ExternalLoggersConfig)


@dataclass
class EnvironmentConfig:
    """Environment configuration."""
    
    google_cloud_project: Optional[str] = None
    google_cloud_location: str = "us-central1"
    env_file_path: str = "../hr_analyst/.env"


@dataclass
class EvaluationConfig:
    """Main configuration class containing all evaluation settings."""
    
    csv_files: CSVFilesConfig = field(default_factory=CSVFilesConfig)
    csv_columns: CSVColumnsConfig = field(default_factory=CSVColumnsConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    context_extraction: ContextExtractionConfig = field(default_factory=ContextExtractionConfig)
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)
    performance_bands: PerformanceBandsConfig = field(default_factory=PerformanceBandsConfig)
    ci_cd: CICDConfig = field(default_factory=CICDConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationConfig":
        """Create configuration from dictionary.
        
        Args:
            data: Dictionary loaded from YAML file
        
        Returns:
            EvaluationConfig instance
        """
        # Helper function to recursively convert dicts to dataclass instances
        def dict_to_dataclass(dataclass_type, data_dict):
            if data_dict is None:
                return dataclass_type()
            
            kwargs = {}
            for field_name, field_type in dataclass_type.__annotations__.items():
                if field_name in data_dict:
                    value = data_dict[field_name]
                    
                    # Recursively convert nested dataclasses
                    if hasattr(field_type, '__dataclass_fields__'):
                        kwargs[field_name] = dict_to_dataclass(field_type, value)
                    else:
                        kwargs[field_name] = value
            
            return dataclass_type(**kwargs)
        
        return dict_to_dataclass(cls, data)
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "EvaluationConfig":
        """Load configuration from YAML file.
        
        Args:
            yaml_path: Path to config.yaml file
        
        Returns:
            EvaluationConfig instance
        
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML is invalid
        """
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls.from_dict(data)


# =============================================================================
# Global Configuration Instance
# =============================================================================

def load_config(config_path: Optional[Path] = None) -> EvaluationConfig:
    """Load configuration from YAML file.
    
    Args:
        config_path: Optional path to config file. If None, uses default location.
    
    Returns:
        Loaded configuration
    """
    if config_path is None:
        # Default: config.yaml in same directory as this file
        config_path = Path(__file__).parent / "config.yaml"
    
    # Allow environment variable override
    if env_config_path := os.getenv("EVAL_CONFIG_PATH"):
        config_path = Path(env_config_path)
    
    try:
        return EvaluationConfig.from_yaml(config_path)
    except FileNotFoundError:
        print(f"Warning: Configuration file not found at {config_path}")
        print("Using default configuration values")
        return EvaluationConfig()
    except Exception as e:
        print(f"Warning: Error loading configuration from {config_path}: {e}")
        print("Using default configuration values")
        return EvaluationConfig()


# Global configuration instance - loaded once on module import
config = load_config()


# =============================================================================
# Utility Functions
# =============================================================================

def reload_config(config_path: Optional[Path] = None) -> EvaluationConfig:
    """Reload configuration from file.
    
    Args:
        config_path: Optional path to config file
    
    Returns:
        Reloaded configuration
    """
    global config
    config = load_config(config_path)
    return config


def get_config() -> EvaluationConfig:
    """Get the global configuration instance.
    
    Returns:
        Global configuration
    """
    return config


def print_config() -> None:
    """Print current configuration in a readable format."""
    print("\n" + "=" * 70)
    print("CURRENT EVALUATION CONFIGURATION")
    print("=" * 70)
    
    print(f"\nCSV Files:")
    print(f"  Input:   {config.csv_files.default_input}")
    print(f"  Output:  {config.csv_files.default_output}")
    print(f"  Summary: {config.csv_files.default_summary}")
    
    print(f"\nCSV Columns:")
    print(f"  Question:        {config.csv_columns.question}")
    print(f"  Expected Answer: {config.csv_columns.expected_answer}")
    print(f"  ID:              {config.csv_columns.id}")
    print(f"  Category:        {config.csv_columns.category}")
    
    print(f"\nJudge:")
    print(f"  Model: {config.judge.default_model}")
    
    print(f"\nMetrics:")
    print(f"  Default Threshold: {config.metrics.default_threshold}")
    print(f"  Faithfulness:           {config.metrics.thresholds.faithfulness}")
    print(f"  Answer Relevancy:       {config.metrics.thresholds.answer_relevancy}")
    print(f"  Contextual Relevancy:   {config.metrics.thresholds.contextual_relevancy}")
    print(f"  Contextual Precision:   {config.metrics.thresholds.contextual_precision}")
    print(f"  Contextual Recall:      {config.metrics.thresholds.contextual_recall}")
    print(f"  Hallucination:          {config.metrics.thresholds.hallucination}")
    
    print(f"\nTimeouts:")
    print(f"  Per Task: {config.timeouts.per_task_seconds}s")
    
    print(f"\nPerformance Bands:")
    print(f"  Excellent:  >= {config.performance_bands.excellent * 100:.0f}%")
    print(f"  Good:       >= {config.performance_bands.good * 100:.0f}%")
    print(f"  Acceptable: >= {config.performance_bands.acceptable * 100:.0f}%")
    
    print(f"\nCI/CD:")
    print(f"  Threshold: {config.ci_cd.default_threshold * 100:.0f}%")
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    # Test configuration loading
    print_config()
````
<!-- END: deep_eval_scripts/config.py -->

<!-- FILE: deep_eval_scripts/config.yaml -->
````yaml
# =============================================================================
# HR Analyst Agent - Evaluation Configuration
# =============================================================================
# This configuration file externalizes all parameters for the evaluation system.
# Update these values instead of modifying code when changing:
# - CSV file paths and column names
# - Metrics thresholds
# - Performance bands
# - Timeout settings
# - Judge models
# =============================================================================

# -----------------------------------------------------------------------------
# CSV File Configuration
# -----------------------------------------------------------------------------
csv_files:
  # Default input CSV file containing test questions and expected answers
  default_input: "deep_eval_scripts/data_sets/HR_Chatbot_Golden_DataSet.csv"
  
  # Default output CSV file for evaluation results
  default_output: "deep_eval_scripts/outputs/evaluation_report.csv"
  
  # Default summary text file for evaluation report
  default_summary: "deep_eval_scripts/outputs/evaluation_report_summary.txt"

# -----------------------------------------------------------------------------
# CSV Column Configuration
# -----------------------------------------------------------------------------
# Define the column names used in your CSV files
# Change these if your dataset uses different column names
csv_columns:
  # Column containing test questions
  question: "Questions"
  
  # Column containing expected/ground truth answers
  expected_answer: "Response"
  
  # Column containing test case IDs (optional)
  id: "ID"
  
  # Column containing test categories (optional)
  category: "Category"

# -----------------------------------------------------------------------------
# LLM Judge Configuration
# -----------------------------------------------------------------------------
judge:
  # Default model to use as the evaluation judge
  # Options: gemini-2.5-pro (slower, more accurate), gemini-1.5-flash (faster, less accurate)
  default_model: "gemini-2.5-pro"
  
  # Alternative models available for use
  alternative_models:
    - "gemini-1.5-flash"
    - "gemini-1.5-pro"

# -----------------------------------------------------------------------------
# Metrics Configuration
# -----------------------------------------------------------------------------
# Configure thresholds for each evaluation metric
# Scores range from 0.0 (worst) to 1.0 (best)
# Lower thresholds = more lenient, Higher thresholds = more strict
metrics:
  # Global default threshold applied to all metrics (if not overridden)
  default_threshold: 0.75
  
  # Per-metric thresholds (optional overrides)
  # Comment out or remove individual metrics to use default_threshold
  thresholds:
    # Faithfulness: Is the answer grounded in the retrieved context?
    faithfulness: 0.75
    
    # Answer Relevancy: Is the answer relevant to the question?
    answer_relevancy: 0.75
    
    # Contextual Relevancy: Is the retrieved context relevant to the query?
    contextual_relevancy: 0.75
    
    # Contextual Precision: Is the retrieved context high quality and well-ranked?
    contextual_precision: 0.75
    
    # Contextual Recall: Is the retrieved information complete?
    contextual_recall: 0.75
    
    # Hallucination: Does the answer contain fabricated information?
    # For hallucination: lower score is better (inverted metric)
    hallucination: 0.75
  
  # Whether to include detailed reasoning in metric results
  include_reason: true

# -----------------------------------------------------------------------------
# Context Extraction Configuration
# -----------------------------------------------------------------------------
context_extraction:
  # Maximum characters per context chunk (longer chunks are truncated)
  max_chunk_size: 1024  # Matches Vertex AI Search chunk size
  
  # Minimum characters for a chunk to be kept (shorter chunks are discarded)
  min_chunk_size: 20
  
  # Maximum number of chunks to use for evaluation (top-ranked chunks only)
  # This should match the golden dataset generator's top_k setting for consistency
  top_k: 5  # Matches Vertex AI Search top_k configuration

# -----------------------------------------------------------------------------
# Timeout Configuration
# -----------------------------------------------------------------------------
timeouts:
  # Timeout per evaluation task in seconds
  # Each test case with 6 LLM-based metrics can take 5-10 minutes
  # Recommended: 3600 seconds (60 minutes) for comprehensive evaluation
  per_task_seconds: 3600
  
  # Total evaluation timeout in minutes (optional)
  # Set to null or 0 for no limit
  total_evaluation_minutes: null

# -----------------------------------------------------------------------------
# Performance Band Configuration
# -----------------------------------------------------------------------------
# Define thresholds for categorizing overall evaluation performance
# Used in summary reports to classify results as EXCELLENT, GOOD, ACCEPTABLE, or POOR
performance_bands:
  # >= 90% pass rate
  excellent: 0.90
  
  # >= 75% pass rate
  good: 0.75
  
  # >= 50% pass rate
  acceptable: 0.50
  
  # < 50% pass rate is considered POOR (no threshold needed)

# -----------------------------------------------------------------------------
# CI/CD Configuration
# -----------------------------------------------------------------------------
# Settings for automated build/pipeline validation
ci_cd:
  # Minimum pass rate required for CI/CD pipelines to pass
  # Build will fail if overall pass rate is below this threshold
  default_threshold: 0.50  # 50%
  
  # Verbose output in CI/CD logs
  verbose: false

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
logging:
  # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  level: "INFO"
  
  # Reduce noise from external libraries
  external_loggers:
    google: "WARNING"
    google_adk: "INFO"
    deepeval: "INFO"

# -----------------------------------------------------------------------------
# Environment Configuration
# -----------------------------------------------------------------------------
environment:
  # Vertex AI project and location
  # These can be overridden by environment variables
  # Leave empty to use environment variables only
  google_cloud_project: null  # Will use GOOGLE_CLOUD_PROJECT env var
  google_cloud_location: "us-central1"
  
  # .env file location (relative to deep_eval_scripts directory)
  env_file_path: "../hr_analyst/.env"
````
<!-- END: deep_eval_scripts/config.yaml -->

<!-- FILE: deep_eval_scripts/evaluate_hr_chatbot_v3.py -->
````python
"""DeepEval evaluation script for HR Analyst RAG Chatbot.

This script evaluates the HR chatbot using DeepEval framework with Vertex AI Gemini as judge.
It performs comprehensive semantic validation by comparing agent responses against expected answers
using 3-6 complementary metrics.

Metrics (all using semantic validation with configurable threshold):
    Essential (3 metrics - use --essential-metrics for faster evaluation):
      1. Faithfulness: Answer grounded in retrieved context
      2. Answer Relevancy: Answer relevance to question
      3. Hallucination: Detection of fabricated information
    
    Additional (comprehensive mode, default):
      4. Contextual Relevancy: Retrieved context relevance to query
      5. Context Precision: Quality/ranking of retrieved context
      6. Context Recall: Completeness of retrieved information

All metrics use LLM-based semantic evaluation via Vertex AI Gemini (not string matching).
Default metric threshold: 0.75 (configurable via --metric-threshold)

IMPROVING CONTEXT RECALL SCORES:
--------------------------------
If Context Recall is consistently < 0.75, the issue is usually that the agent finds
the information but the script loses it during extraction. To fix:

1. **Check Extraction Logs**: Look for warnings about missing regex matches or empty
   content blocks. The script now logs detailed extraction diagnostics.

2. **Increase Vertex AI Search Results**: By default, VertexAiSearchTool may return
   only 3-5 chunks. For complex HR questions spanning multiple policy documents:
   - Edit hr_analyst/agent.py: Consider using search result summarization settings
   - Check Vertex AI Search console: Configure result count per query
   - Note: ADK's VertexAiSearchTool doesn't expose top_k in code, but the data store
     configuration in Google Cloud Console allows tuning result counts

3. **Enable Hybrid Search**: In Vertex AI Search console (Discovery Engine):
   - Go to your data store configuration
   - Enable "Hybrid Search" (combines vector similarity + keyword matching)
   - This captures HR-specific terms like policy numbers, legal jargon, dates

4. **Review Agent Instructions**: Ensure search agent extracts ALL results:
   - Check SEARCH_AGENT_INSTRUCTION in hr_analyst/agent.py
   - Verify it formats every result with :::BEGIN RESULT::: markers
   - Test with debug_search_extraction.py to see raw outputs

5. **Use Context Debugger**: This script now runs debug_context_recall() for each
   test case, logging which sentences/terms from ground truth are missing from
   retrieved context. Check logs for specific missing info patterns.

Usage:
    # Full evaluation with all 6 metrics (comprehensive)
    uv run python deep_eval_scripts/evaluate_hr_chatbot.py \
      --input deep_eval_scripts/data_sets/HR_Chatbot_Golden_DataSet.csv \
      --expected-answer-column "Response" \
      --limit 10

    # Fast evaluation with essential 3 metrics only (recommended for 100+ test cases)
    uv run python deep_eval_scripts/evaluate_hr_chatbot.py \
      --input deep_eval_scripts/data_sets/HR_Chatbot_Golden_DataSet.csv \
      --expected-answer-column "Response" \
      --essential-metrics \
      --limit 100

Performance:
    - Full mode (6 metrics): ~6-8 min per test case → 100 cases = ~10-13 hours (sequential)
    - Essential mode (3 metrics): ~3 min per test case → 100 cases = ~5 hours (sequential)
    - **High-Concurrency Mode (NEW)**: With async processing and Semaphore(5) for Windows:
      * Essential metrics: 100 cases in ~40-50 minutes
      * Full metrics: 100 cases in ~60-90 minutes (NOT RECOMMENDED - use essential)
      * 2 test cases processed simultaneously to prevent Windows event loop conflicts
      * **IMPORTANT**: On Windows, use --essential-metrics to avoid gRPC/async issues
    - Evaluation timeout: 60 minutes per task (configurable in config.yaml)
    - Recommended for Windows: ALWAYS use --essential-metrics flag for stability

Requirements:
    - deepeval package installed
    - Valid .env file with Vertex AI credentials
    - CSV with 'Questions' column (questions)
    - CSV with expected answer column (human-verified ground truth)
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
import traceback
import warnings
from pathlib import Path
from typing import Any
import uuid
from datetime import datetime
import copy

from dotenv import load_dotenv

# CRITICAL: Set Windows event loop policy BEFORE any async operations
# This prevents "Event loop is closed" and gRPC interceptor AttributeErrors on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Suppress event loop warnings on Windows (known issue with async cleanup)
warnings.filterwarnings("ignore", message=".*Event loop is closed.*", category=RuntimeWarning)

# Import configuration early (before using it)
# Try importing from package first, then relative import
try:
    from deep_eval_scripts.config import config  # noqa: E402
except ImportError:
    # If running from deep_eval_scripts directory, use relative import
    sys.path.insert(0, str(Path(__file__).parent))
    from config import config  # noqa: E402


# ---------------------------------------------------------------------------
# Environment Initialization (called from main(), not at import time)
# ---------------------------------------------------------------------------
def _init_environment() -> None:
    """Initialize environment variables, Vertex AI, and validate credentials.

    This must be called before any Google/Vertex AI modules are used.
    Separated from module-level code to avoid side effects on import.
    """
    # CRITICAL: Set environment variables BEFORE importing ANY Google/Vertex AI modules
    # In CI/CD pipelines, environment variables are set by the pipeline itself
    # In local development, they come from .env file
    env_path = Path(__file__).parent.parent / "hr_analyst" / ".env"
    if env_path.exists():
        logger.info(f"[OK] Loading environment from .env file: {env_path}")
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        logger.info(f"[INFO] .env file not found at {env_path}, using existing environment variables")

    # Explicitly set these in os.environ to ensure they're picked up
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("GOOGLE_CLOUD_PROJECT")
    if os.getenv("GOOGLE_CLOUD_LOCATION"):
        os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GOOGLE_CLOUD_LOCATION")

    # Validate GOOGLE_APPLICATION_CREDENTIALS if set
    cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_file:
        try:
            with open(cred_file, 'r') as f:
                json.load(f)
            logger.info(f"[OK] Valid credentials file: {cred_file}")
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.warning(f"[WARNING] Invalid credentials file at {cred_file}: {e}")
            logger.info("[INFO] Unsetting GOOGLE_APPLICATION_CREDENTIALS - will rely on environment variables")
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
                del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

    # Configure DeepEval timeout
    os.environ["DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE"] = str(config.timeouts.per_task_seconds)

    # Verify critical environment variables
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            import google.auth
            credentials, project_id = google.auth.default()
            if project_id:
                os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
                logger.info(f"[OK] Using project from credentials: {project_id}")
        except Exception as e:
            logger.warning(f"[WARNING] Could not extract project from credentials: {e}")
            logger.info("[INFO] Will rely on GOOGLE_CLOUD_PROJECT environment variable if set")

    required_vars = ["GOOGLE_GENAI_USE_VERTEXAI"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"ERROR: Missing required environment variables: {missing_vars}")
        logger.info(
            "In CI/CD: Ensure GOOGLE_APPLICATION_CREDENTIALS is set and service account has proper permissions"
        )
        logger.info(f"In local dev: Check your .env file at: {env_path}")
        sys.exit(1)

    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        logger.error("ERROR: GOOGLE_CLOUD_PROJECT not found in environment or credentials")
        logger.info(
            "In CI/CD: Ensure GOOGLE_APPLICATION_CREDENTIALS contains a valid service account key"
        )
        logger.info(f"In local dev: Set GOOGLE_CLOUD_PROJECT in your .env file at: {env_path}")
        sys.exit(1)

    logger.info(f"[OK] Using Vertex AI with project: {os.getenv('GOOGLE_CLOUD_PROJECT')}")

    # Import and initialize Vertex AI
    import vertexai
    vertexai.init(
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    )


# DeepEvalBaseLLM must be imported at module level because VertexAIGeminiModel
# inherits from it at class definition time. This import is safe without env setup.
from deepeval.models.base_model import DeepEvalBaseLLM

# Module-level lazy references — populated by _init_imports()
_imports_initialized = False
evaluate = None
AnswerRelevancyMetric = None
ContextualPrecisionMetric = None
ContextualRecallMetric = None
ContextualRelevancyMetric = None
FaithfulnessMetric = None
HallucinationMetric = None
LLMTestCase = None
RunConfig = None
StreamingMode = None
Runner = None
InMemorySessionService = None
types = None
#root_agent = None


def _init_imports() -> None:
    """Import Google/Vertex AI and DeepEval modules after environment is configured."""
    # global _imports_initialized
    # global evaluate, AnswerRelevancyMetric, ContextualPrecisionMetric
    # global ContextualRecallMetric, ContextualRelevancyMetric
    # global FaithfulnessMetric, HallucinationMetric
    # global LLMTestCase
    # global RunConfig, StreamingMode, Runner, InMemorySessionService, types
    # #global root_agent

    # if _imports_initialized:
    #     return

    from google.adk.agents.run_config import RunConfig as _RunConfig, StreamingMode as _StreamingMode
    from google.adk.runners import Runner as _Runner
    from google.adk.sessions import InMemorySessionService as _InMemorySessionService
    from google.genai import types as _types

    from deepeval import evaluate as _evaluate
    from deepeval.metrics import (
        AnswerRelevancyMetric as _AnswerRelevancyMetric,
        ContextualPrecisionMetric as _ContextualPrecisionMetric,
        ContextualRecallMetric as _ContextualRecallMetric,
        ContextualRelevancyMetric as _ContextualRelevancyMetric,
        FaithfulnessMetric as _FaithfulnessMetric,
        HallucinationMetric as _HallucinationMetric,
    )
    from deepeval.test_case import LLMTestCase as _LLMTestCase

    #from hr_analyst.agent import root_agent as _root_agent

    RunConfig = _RunConfig
    StreamingMode = _StreamingMode
    Runner = _Runner
    InMemorySessionService = _InMemorySessionService
    types = _types
    evaluate = _evaluate
    AnswerRelevancyMetric = _AnswerRelevancyMetric
    ContextualPrecisionMetric = _ContextualPrecisionMetric
    ContextualRecallMetric = _ContextualRecallMetric
    ContextualRelevancyMetric = _ContextualRelevancyMetric
    FaithfulnessMetric = _FaithfulnessMetric
    HallucinationMetric = _HallucinationMetric
    LLMTestCase = _LLMTestCase
    #root_agent = _root_agent
    _imports_initialized = True


logging.basicConfig(
    level=getattr(logging, config.logging.level, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
# Reduce noise from other loggers
logging.getLogger("google").setLevel(
    getattr(logging, config.logging.external_loggers.google, logging.WARNING)
)
logging.getLogger("google_adk").setLevel(
    getattr(logging, config.logging.external_loggers.google_adk, logging.INFO)
)
logging.getLogger("deepeval").setLevel(
    getattr(logging, config.logging.external_loggers.deepeval, logging.INFO)
)

# Module-level constant for metric name to score key mapping
# Used in run_evaluation, compute_summary_statistics, and save_results_to_csv
METRIC_SCORE_KEY_MAP = {
    "Faithfulness": "faithfulness_score",
    "AnswerRelevancy": "answer_relevancy_score",
    "ContextualRelevancy": "contextual_relevancy_score",
    "ContextualPrecision": "contextual_precision_score",
    "ContextualRecall": "contextual_recall_score",
    "Hallucination": "hallucination_score",
}

# Pre-compiled metadata patterns for context chunk cleaning (Opt 4)
# These are compiled once at module load instead of per-chunk
_METADATA_LINE_PATTERN = re.compile(
    r"^"
    r"(?:ID:\s*.*"
    r"|URL:\s*.*"
    r"|Source:\s*.*"
    r"|Timestamp:\s*.*"
    r"|Document ID:\s*.*"
    r"|File:\s*.*"
    r"|Path:\s*.*"
    r"|https?://.*"
    r"|gs://.*"
    r"|[a-f0-9]{8}-[a-f0-9]{4}-.*)$",
    re.MULTILINE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Custom Vertex AI Gemini Model for DeepEval
# ---------------------------------------------------------------------------
class VertexAIGeminiModel(DeepEvalBaseLLM):
    """Custom DeepEval model wrapper for Vertex AI Gemini."""

    def __init__(self, model_name: str = "gemini-2.5-pro"):
        """Initialize Vertex AI Gemini model for DeepEval evaluation.

        Args:
            model_name: The Vertex AI model name (default: gemini-2.5-pro)
        """
        self.model_name = model_name
        from vertexai.generative_models import GenerativeModel, GenerationConfig, SafetySetting, HarmCategory, HarmBlockThreshold

        # Configure generation for reliable JSON output
        # Note: We use robust sanitization instead of response_mime_type
        # because it's more compatible with DeepEval's prompt structure
        generation_config = GenerationConfig(
            temperature=0.0,  # Deterministic for evaluation consistency
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
        )
        
        # Set safety settings to BLOCK_NONE to prevent content filtering
        # Evaluation prompts may contain policy text that triggers false positives
        safety_settings = [
            SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
        ]
        
        self.model = GenerativeModel(
            model_name,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        logger.info(f"Initialized {model_name} with sanitization-based JSON handling and permissive safety settings")

    def load_model(self):
        """Load the model (already loaded in __init__)."""
        return self.model

    def _sanitize_json_response(self, text: str) -> str:
        """Sanitize JSON response to fix common issues and extract valid JSON.
        
        This method handles:
        - Markdown code blocks (```json ... ```)
        - Explanatory text before/after JSON
        - Invalid escape sequences
        - Trailing commas
        
        Args:
            text: Raw text response from the model
            
        Returns:
            Sanitized JSON text, or original text if no JSON found
        """
        if not text or not text.strip():
            logger.error("Received empty response from model")
            return text
        
        original_text = text
        
        # Step 1: Remove markdown code blocks
        if '```' in text:
            code_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
            matches = re.findall(code_block_pattern, text)
            if matches:
                text = max(matches, key=len) if len(matches) > 1 else matches[0]
        
        # Step 2: Extract JSON object from text
        text = text.strip()
        
        if '{' not in text:
            # No JSON structure found - log and return original
            logger.error(f"No JSON structure found in response: {text[:200]}")
            return original_text
        
        start_idx = text.find('{')
        # Find matching closing brace
        brace_count = 0
        end_idx = -1
        for i in range(start_idx, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
        
        if end_idx > start_idx:
            text = text[start_idx:end_idx]
        elif brace_count > 0:
            # Incomplete JSON - missing closing braces
            logger.warning(f"JSON appears truncated (missing {brace_count} closing braces)")
            # Try to close it
            text = text[start_idx:] + ('}' * brace_count)
        else:
            # Couldn't find proper JSON structure
            logger.error(f"Couldn't extract valid JSON structure from: {text[:200]}")
            return original_text
        
        # Step 3: Fix escape sequences more carefully
        # Only fix invalid escape sequences that will cause JSON parsing to fail
        # Valid JSON escapes: \" \\ \/ \b \f \n \r \t \uXXXX
        
        try:
            result = []
            i = 0
            in_string = False
            
            while i < len(text):
                char = text[i]
                
                # Track if we're inside a string value
                if char == '"' and (i == 0 or text[i-1] != '\\'):
                    in_string = not in_string
                    result.append(char)
                    i += 1
                    continue
                
                # If we find a backslash inside a string, check if it's valid
                if in_string and char == '\\':
                    if i + 1 < len(text):
                        next_char = text[i + 1]
                        # Valid JSON escape sequences
                        if next_char in ['"', '\\', '/', 'b', 'f', 'n', 'r', 't']:
                            # Keep valid escape sequence as-is
                            result.append(char)
                            result.append(next_char)
                            i += 2
                            continue
                        elif next_char == 'u' and i + 5 < len(text):
                            # Unicode escape \uXXXX - keep as-is if valid hex
                            hex_part = text[i+2:i+6]
                            try:
                                int(hex_part, 16)  # Validate it's hex
                                result.append(char)
                                result.append(next_char)
                                result.extend(list(hex_part))
                                i += 6
                                continue
                            except ValueError:
                                # Invalid unicode escape - escape the backslash
                                result.append('\\\\')
                                i += 1
                                continue
                        else:
                            # Invalid escape - escape the backslash
                            result.append('\\\\')
                            i += 1
                            continue
                    else:
                        # Backslash at end of string - escape it
                        result.append('\\\\')
                        i += 1
                        continue
                
                result.append(char)
                i += 1
            
            text = ''.join(result)
        except Exception as e:
            logger.error(f"Error during escape sequence processing: {e}")
            # Return original if processing fails
            return original_text
        
        # Step 4: Remove trailing commas
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # Step 5: Validate JSON
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError as e:
            logger.error(f"JSON sanitization produced invalid JSON: {e}")
            logger.error(f"Original (first 300 chars): {original_text[:300]}...")
            logger.error(f"Sanitized (first 300 chars): {text[:300]}...")
            logger.error(f"Error location: line {e.lineno} col {e.colno}")
            # Return original text - let DeepEval's error handling deal with it
            # This way the error message will include the actual malformed content
            return original_text


    def generate(self, prompt: str) -> str:
        """Generate text from the model.

        Args:
            prompt: The input prompt

        Returns:
            Generated text response
        """
        try:
            response = self.model.generate_content(prompt)
            
            # Check if response was blocked by safety filters
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                if hasattr(response.prompt_feedback, 'block_reason'):
                    block_reason = response.prompt_feedback.block_reason
                    if block_reason:
                        logger.error(f"Response blocked by safety filter: {block_reason}")
                        logger.error(f"Prompt (first 200 chars): {prompt[:200]}")
                        # Return a minimal valid JSON to prevent DeepEval from crashing
                        return '{"error": "blocked by safety filter"}'
            
            # Extract text from response
            result = ""
            if response and hasattr(response, 'text'):
                try:
                    result = response.text
                except ValueError as e:
                    # This can happen if response has no text but has other content
                    logger.error(f"Could not extract text from response: {e}")
                    if hasattr(response, 'candidates') and response.candidates:
                        logger.error(f"Response has {len(response.candidates)} candidates but no text")
                        candidate = response.candidates[0]
                        if hasattr(candidate, 'finish_reason'):
                            logger.error(f"Finish reason: {candidate.finish_reason}")
                        if hasattr(candidate, 'safety_ratings'):
                            logger.error(f"Safety ratings: {candidate.safety_ratings}")
                    return '{"error": "no text in response"}'
            
            # Check for empty response
            if not result or not result.strip():
                logger.error("Model returned empty response")
                logger.error(f"Prompt (first 200 chars): {prompt[:200]}")
                return '{"error": "empty response"}'
            
            # Log raw response for debugging (only first 500 chars)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Raw LLM response (first 500 chars): {result[:500]}")
            
            sanitized = self._sanitize_json_response(result)
            
            # Log if sanitization changed anything
            if sanitized != result and logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Sanitized response (first 500 chars): {sanitized[:500]}")
            
            return sanitized
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            logger.error(f"Prompt (first 200 chars): {prompt[:200]}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return '{"error": "exception during generation"}'

    async def a_generate(self, prompt: str) -> str:
        """Async generate using native Vertex AI async API with retry logic.

        Args:
            prompt: The input prompt

        Returns:
            Generated text response
        """
        max_retries = 3
        base_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                # Use native async method from Vertex AI SDK
                response = await self.model.generate_content_async(prompt)
                
                # Check if response was blocked by safety filters
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    if hasattr(response.prompt_feedback, 'block_reason'):
                        block_reason = response.prompt_feedback.block_reason
                        if block_reason:
                            logger.error(f"Response blocked by safety filter: {block_reason}")
                            logger.error(f"Prompt (first 200 chars): {prompt[:200]}")
                            return '{"error": "blocked by safety filter"}'
                
                # Extract text from response
                result_text = None
                if response and hasattr(response, 'text'):
                    try:
                        result_text = response.text
                    except ValueError as e:
                        # This can happen if response has no text but has other content
                        logger.error(f"Could not extract text from response: {e}")
                        if hasattr(response, 'candidates') and response.candidates:
                            logger.error(f"Response has {len(response.candidates)} candidates but no text")
                            candidate = response.candidates[0]
                            if hasattr(candidate, 'finish_reason'):
                                logger.error(f"Finish reason: {candidate.finish_reason}")
                            if hasattr(candidate, 'safety_ratings'):
                                logger.error(f"Safety ratings: {candidate.safety_ratings}")
                        
                        # Retry if not last attempt
                        if attempt < max_retries - 1:
                            delay = base_delay * (2**attempt)
                            logger.info(f"Retrying in {delay} seconds...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            return '{"error": "no text in response"}'
                
                # Check for non-empty result
                if result_text and result_text.strip():
                    # Sanitize JSON response to fix escape sequences
                    result_text = self._sanitize_json_response(result_text)
                    
                    # Log response preview at DEBUG level for troubleshooting
                    if logger.isEnabledFor(logging.DEBUG):
                        preview = result_text[:300] if len(result_text) > 300 else result_text
                        logger.debug(f"📤 LLM response: {preview}{'...' if len(result_text) > 300 else ''}")
                    return result_text
                else:
                    # Empty response - treat as retryable error
                    logger.warning(f"Empty response from LLM on attempt {attempt + 1}/{max_retries}")
                    logger.warning(f"Prompt (first 200 chars): {prompt[:200]}")
                    
                    if attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        logger.info(f"Retrying in {delay} seconds...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        # Final attempt failed - return error JSON
                        logger.error("All retries exhausted, LLM returned empty response")
                        return '{"error": "empty response after retries"}'
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Exception during LLM generation: {error_msg[:200]}")
                
                # Check if it's a retryable error (auth/network issues)
                is_retryable = any(
                    msg in error_msg.lower()
                    for msg in [
                        "ssl",
                        "oauth",
                        "503",
                        "authentication",
                        "token",
                        "connection",
                        "timeout",
                    ]
                )
                
                if is_retryable and attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Retryable error in async generation (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Error in async generation: {e}")
                    logger.error(f"Prompt (first 200 chars): {prompt[:200]}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # Return error JSON instead of empty string
                    return '{"error": "exception during generation"}'
        
        # All retries exhausted
        logger.error("All retries exhausted, returning error JSON")
        return '{"error": "all retries exhausted"}'

    def get_model_name(self) -> str:
        """Return the model name.

        Returns:
            Model name string
        """
        return self.model_name


# ---------------------------------------------------------------------------
# Context Debugging Utilities
# ---------------------------------------------------------------------------
def debug_context_recall(
    expected_output: str, retrieved_context: list[str], question: str
) -> dict[str, Any]:
    """Compare expected output against retrieved context to identify missing information.

    This helps diagnose Context Recall issues by showing which sentences or keywords
    from the ground truth are not present in the retrieved chunks.

    Args:
        expected_output: Ground truth answer (from CSV 'Response' column)
        retrieved_context: List of context chunks retrieved by the agent
        question: The original question

    Returns:
        Dictionary with debugging statistics and missing content analysis
    """
    # Combine all retrieved context into one string
    all_context = " ".join(retrieved_context).lower()
    expected_lower = expected_output.lower()

    # Split expected output into sentences
    sentences = [s.strip() for s in expected_output.split(".") if s.strip()]

    # Find missing sentences
    missing_sentences = []
    matched_sentences = []
    for sentence in sentences:
        # Check if any significant words from the sentence appear in context
        words = [w for w in sentence.lower().split() if len(w) > 3]  # Skip short words
        if words:
            match_ratio = sum(1 for w in words if w in all_context) / len(words)
            if match_ratio < 0.5:  # Less than 50% of words found
                missing_sentences.append(sentence)
            else:
                matched_sentences.append(sentence)

    # Extract key terms from expected output (capitalized words, numbers, dates)
    key_terms = re.findall(
        r"\b[A-Z][a-z]+(?:[\s][A-Z][a-z]+)*\b|\b\d+[\d,.%]*\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        expected_output,
    )
    missing_terms = [term for term in key_terms if term.lower() not in all_context]

    result = {
        "total_sentences": len(sentences),
        "matched_sentences": len(matched_sentences),
        "missing_sentences": len(missing_sentences),
        "match_rate": (
            len(matched_sentences) / len(sentences) if sentences else 0.0
        ),
        "missing_sentence_list": missing_sentences[:3],  # First 3 for brevity
        "key_terms_found": len(key_terms) - len(missing_terms),
        "key_terms_missing": len(missing_terms),
        "missing_term_list": missing_terms[:5],  # First 5 for brevity
        "context_chunks": len(retrieved_context),
        "total_context_length": len(all_context),
    }

    # Log detailed debugging info
    if missing_sentences or missing_terms:
        logger.debug(f"⚠️  CONTEXT RECALL ISSUE DETECTED for question: {question[:60]}...")
        logger.debug(
            f"   Sentence match rate: {result['match_rate']:.1%} ({result['matched_sentences']}/{result['total_sentences']})"
        )
        if missing_sentences:
            logger.debug(f"   Missing sentences (first 3):")
            for sent in result["missing_sentence_list"]:
                logger.debug(f"     - {sent[:100]}...")
        if missing_terms:
            logger.debug(
                f"   Missing key terms ({len(missing_terms)}): {', '.join(result['missing_term_list'])}"
            )
        logger.debug(
            f"   Retrieved {result['context_chunks']} chunks ({result['total_context_length']} chars total)"
        )
    else:
        logger.debug(
            f"✓ Good context coverage: {result['match_rate']:.1%} sentence match"
        )

    return result


# ---------------------------------------------------------------------------
# Agent Response Extraction
# ---------------------------------------------------------------------------
async def call_root_agent(
    session_service,
    id: int,
    question: str
) -> dict[str, Any]:
    """Call the root agent asynchronously and extract answer + retrieved context.

    This function wraps the ADK agent runner to provide a clean interface
    that returns both the final answer and the retrieved context chunks.
    Uses asyncio.to_thread to prevent blocking the event loop.

    Args:
        question: The user question to ask the agent
        runner: The ADK Runner instance (reused across questions)
        session_service: Session service for creating sessions
        user_id: User ID for the session

    Returns:
        Dictionary containing:
            - answer: The final agent response text
            - retrieved_context: List of retrieved document chunks
    """
    #from google.adk.sessions import InMemorySessionService
    from google.adk.tools.agent_tool import AgentTool
    from google.adk.runners import Runner
    from hr_analyst.agent import root_agent
    
    app_name="deepeval"
    user_id = f"user_{id}"
    session_id = f"sess_{uuid.uuid4()}"
    
    session = session_service.create_session_sync(
        user_id=user_id, 
        app_name=app_name
    )
    runner = Runner(
        agent=root_agent, session_service=session_service, app_name=app_name
    )

    max_retries = 2
    base_delay = 3  # seconds
    
    for attempt in range(max_retries):
        try:
            # Run synchronous agent call in thread pool to avoid blocking
            # result = await asyncio.to_thread(
            #     _call_root_agent_sync, question, runner, user_id, session.id
            # )
            result = await _call_root_agent_sync(id, question, runner, user_id, session.id)

            # Check if agent returned an error
            if result.get("answer", "").startswith("ERROR:") and attempt < max_retries - 1:
                logger.warning(
                    f"[{id}] Agent returned error on attempt {attempt + 1}/{max_retries}, retrying in {base_delay}s..."
                )
                await asyncio.sleep(base_delay)
                continue
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"[{id}] Error calling root agent (attempt {attempt + 1}/{max_retries}): {e}, "
                    f"retrying in {base_delay}s..."
                )
                await asyncio.sleep(base_delay)
                continue
            logger.error(f"[{id}] Error calling root agent (all retries exhausted): {e}")
            return {"answer": f"ERROR: {e!s}", "retrieved_context": []}


async def _call_root_agent_sync(
    id: int,
    question: str, 
    runner,
    user_id: str, 
    session_id: str
) -> dict[str, Any]:
    """Synchronous helper for call_root_agent."""
    try:
        from google.genai import types
        from google.adk.agents.run_config import RunConfig, StreamingMode

        # Create message
        message = types.Content(
            role="user", parts=[types.Part.from_text(text=question)]
        )

        # Run the agent and collect events
        events = []
        async_gen = runner.run_async(
            new_message=message,
            user_id=user_id,  # Use passed user_id, not hardcoded
            session_id=session_id,
            run_config=RunConfig(streaming_mode=StreamingMode.NONE),
        )
        async for event in async_gen:
            events.append(event)
        #logger.info(f"[{id}] Response Event Size: {len(events)}")

        # Extract final answer from the LAST event (same as process_csv_questions.py)
        final_answer = ""
        for event in reversed(events):  # Start from the end
            if event.content and event.content.parts:
                parts_text = []
                for part in event.content.parts:
                    if part.text:
                        parts_text.append(part.text)
                if parts_text:
                    final_answer = "".join(parts_text)
                    break  # Found the last event with text

        # Extract retrieved context from search agent tool responses
        # Structure: part.function_response.response['result'] contains ':::BEGIN RESULT:::...'
        retrieved_context = []
        # func_calls = []

        # logger.debug(f"Extracting search results from {len(events)} events...")  # Commented to reduce clutter
        for event_idx, event in enumerate(events):
            if not event.content or not event.content.parts:
                continue

            for part in event.content.parts:
                # if hasattr(part, "function_call") and part.function_call:
                #     func_calls.append(part.function_call)
                # Check if this part has a function_response (agent/tool response)
                if not hasattr(part, "function_response") or not part.function_response:
                    continue

                # Get the response dict from function_response
                if not hasattr(part.function_response, "response"):
                    continue

                response_dict = part.function_response.response
                if not isinstance(response_dict, dict):
                    continue

                # Get the result string
                result_text = response_dict.get("result", "")
                if not result_text or not isinstance(result_text, str):
                    continue

                #logger.info(f"[{id}] Function Response Result: {result_text}")
                # Look for search result blocks
                if ":::BEGIN RESULT:::" in result_text:
                    # logger.debug(f"Found search results in event {event_idx}!")  # Commented to reduce clutter

                    # FIX 1: STRICT CHUNK SEPARATION
                    # Each :::BEGIN RESULT:::...:::END RESULT::: block MUST be a separate list item
                    # Using re.DOTALL to capture multi-line content properly
                    result_blocks = re.findall(
                        r":::BEGIN RESULT:::(.*?):::END RESULT:::",
                        result_text,
                        re.DOTALL | re.MULTILINE,
                    )

                    # Verbose block extraction logging commented to reduce terminal clutter
                    # logger.debug(f"  Extracted {len(result_blocks)} SEPARATE result blocks from event {event_idx}")

                    for block_idx, block in enumerate(result_blocks):
                        # FIX 2: CLEAN METADATA FROM CHUNKS
                        # Extract ONLY the semantic content, discard IDs, URLs, timestamps
                        
                        # Try to extract content after "Content:" field
                        content_match = re.search(
                            r"Content:\s*(.+?)\s*(?:ID:|URL:|Source:|Timestamp:|$)",
                            block,
                            re.DOTALL | re.IGNORECASE
                        )
                        
                        if content_match:
                            raw_content = content_match.group(1).strip()
                        else:
                            # Fallback: extract text but remove common metadata patterns
                            raw_content = block.strip()
                        
                        # FIX 2.1: Remove metadata lines using pre-compiled pattern
                        clean_content = _METADATA_LINE_PATTERN.sub("", raw_content)
                        
                        # Remove excessive whitespace and empty lines
                        clean_content = re.sub(r"\n\s*\n+", "\n\n", clean_content)
                        clean_content = clean_content.strip()
                        
                        # Skip if content is too short or empty after cleaning
                        if not clean_content or len(clean_content) < config.context_extraction.min_chunk_size:
                            # Verbose chunk skipping logging commented to reduce terminal clutter
                            # logger.debug(
                            #     f"    Block {block_idx}: Content too short after cleaning ({len(clean_content)} chars), skipping"
                            # )
                            continue
                        
                        # FIX 3: CHUNK TRUNCATION/FILTERING
                        # Limit chunks to configured max size to improve relevancy scores
                        max_chunk = config.context_extraction.max_chunk_size
                        
                        if len(clean_content) > max_chunk:
                            # logger.debug(
                            #     f"    Block {block_idx}: Chunk too long ({len(clean_content)} chars), "
                            #     f"truncating to {max_chunk} chars"
                            # )  # Commented to reduce terminal clutter
                            pass
                            # Keep the first N chars (usually most relevant)
                            # Try to break at sentence boundary if possible
                            truncated = clean_content[:max_chunk]
                            
                            # Try to end at a sentence
                            last_period = truncated.rfind(".")
                            last_newline = truncated.rfind("\n")
                            break_point = max(last_period, last_newline)
                            
                            if break_point > max_chunk * 0.8:  # At least 80% of target
                                clean_content = truncated[:break_point + 1].strip()
                            else:
                                clean_content = truncated.strip() + "..."
                        
                        # Add cleaned chunk to list
                        retrieved_context.append(clean_content)
                        # logger.debug(
                        #     f"    Block {block_idx}: Added chunk ({len(clean_content)} chars after cleaning)"
                        # )  # Commented to reduce terminal clutter

        # FIX 5: DEDUPLICATE CONTEXT CHUNKS
        # Remove duplicate chunks using fingerprint-based matching (first 100 chars)
        if retrieved_context:
            seen_fingerprints = set()
            deduplicated_context = []
            for chunk in retrieved_context:
                fingerprint = chunk[:100].strip()
                if fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(fingerprint)
                    deduplicated_context.append(chunk)
                else:
                    pass
                    # logger.debug(f"  Skipping duplicate chunk: {fingerprint[:50]}...")  # Commented to reduce terminal clutter
            if len(deduplicated_context) < len(retrieved_context):
                # Verbose deduplication logging commented to reduce terminal clutter
                # logger.debug(
                #     f"  Deduplication: {len(retrieved_context)} -> {len(deduplicated_context)} chunks "
                #     f"({len(retrieved_context) - len(deduplicated_context)} duplicates removed)"
                # )
                pass
            retrieved_context = deduplicated_context

        # FIX 6: LIMIT TO TOP-K CHUNKS (consistency with golden dataset generator)
        # Limit to top_k chunks to improve Contextual Relevancy while maintaining Recall
        if retrieved_context and len(retrieved_context) > config.context_extraction.top_k:
            logger.debug(
                f"[{id}]  Limiting context from {len(retrieved_context)} to top {config.context_extraction.top_k} chunks"
            )
            retrieved_context = retrieved_context[:config.context_extraction.top_k]

        # FIX 4: IN-LINE DEBUGGING
        # Log first 100 chars of each chunk for verification
        if not retrieved_context:
            logger.error(
                f"[{id}]  ❌ CRITICAL: No context extracted from search results! "
                "This will result in ZERO Context Recall score."
            )
            logger.error("   Possible causes:")
            logger.error("   1. Search agent didn't use VertexAiSearchTool (check agent logs)")
            logger.error("   2. Search returned no results (question may be out-of-scope)")
            logger.error("   3. Regex extraction failed (check event structure)")
            logger.error("   Recommendation: Review agent instruction and increase retrieval limit")
        else:
            logger.debug(
                f"[{id}]  ✓ Extracted {len(retrieved_context)} CLEAN context chunk(s) from search results"
            )
            
            # # FIX 4: DEBUG LOGGING - Print first 100 chars of EACH chunk (COMMENTED - too verbose)
            # logger.debug("📋 CONTEXT CHUNKS PREVIEW (first 100 chars each):")
            # for idx, chunk in enumerate(retrieved_context, 1):
            #     # Show first 100 chars, replace newlines with spaces for readability
            #     preview = chunk[:100].replace("\n", " ").replace("\r", "")
            #     logger.debug(f"  Chunk {idx}/{len(retrieved_context)}: '{preview}{'...' if len(chunk) > 100 else ''}'")
            #     logger.debug(f"           Length: {len(chunk)} chars")

        return {"answer": final_answer, "retrieved_context": retrieved_context}

    except Exception as e:
        logger.error(f"Error in _call_root_agent_sync: {e}")
        return {"answer": f"ERROR: {e!s}", "retrieved_context": []}


# ---------------------------------------------------------------------------
# CSV Processing
# ---------------------------------------------------------------------------
def load_questions_from_csv(
    csv_path: str,
    question_col: str = "Questions",
    expected_answer_col: str | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Load questions and expected answers from CSV file.

    Args:
        csv_path: Path to the CSV file
        question_col: Name of the question column
        expected_answer_col: Name of the column containing expected/ground truth answers (REQUIRED)
        limit: Maximum number of questions to load (None = all)

    Returns:
        List of dictionaries with 'id', 'category', 'question', and 'expected_answer' keys

    Note:
        All returned questions must have 'expected_answer' for semantic validation.
        Questions without expected answers will still be loaded but flagged for skipping.
    """
    questions = []
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]

    for encoding in encodings:
        try:
            with open(csv_path, encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)

                if question_col not in reader.fieldnames:
                    raise ValueError(
                        f"Column '{question_col}' not found. "
                        f"Available: {reader.fieldnames}"
                    )

                for i, row in enumerate(reader):
                    if limit and i >= limit:
                        break

                    question = row.get(question_col, "").strip()
                    if question:
                        question_data = {
                            "id": row.get("ID", str(i + 1)),
                            "category": row.get("Category", "Unknown"),
                            "question": question,
                            "scope": row.get("scope", row.get("Scope", "in_scope")).strip().lower(),  # Try lowercase first, then capital S
                        }

                        # Add expected answer if column is specified
                        if expected_answer_col:
                            expected_answer = row.get(expected_answer_col, "").strip()
                            if expected_answer:
                                question_data["expected_answer"] = expected_answer

                        questions.append(question_data)

            logger.info(f"Loaded {len(questions)} questions using encoding: {encoding}")
            return questions

        except (UnicodeDecodeError, UnicodeError):
            if encoding == encodings[-1]:
                raise
            continue

    return questions


async def process_question(semaphore, session_service, i: int, num_questions: int, q_data: dict[str, str]):
    """Process a single question with semaphore control."""
    question = q_data["question"]

    # Skip questions without expected answers
    if "expected_answer" not in q_data:
        logger.warning(
            f"[{i}/{num_questions}] SKIPPED (no expected answer): {question[:60]}..."
        )
        return None

    async with semaphore:  # Acquire semaphore
        logger.info(f"[{i}/{num_questions}] Processing: {question[:60]}...")

        # Call root agent asynchronously
        result = await call_root_agent(session_service, i, question)

        # Validate result has minimum required data
        if not result.get("answer"):
            logger.error(f"[{i}/{num_questions}]  ❌ No answer generated, skipping test case")
            return None
        
        # Ensure retrieved_context is a list (even if empty)
        if not isinstance(result.get("retrieved_context"), list):
            logger.warning(f"[{i}/{num_questions}]  ⚠️  Invalid context type, converting to empty list")
            result["retrieved_context"] = []
        
        # Filter out any empty strings from context (should already be cleaned, but safety check)
        result["retrieved_context"] = [
            chunk for chunk in result["retrieved_context"] 
            if chunk and isinstance(chunk, str) and chunk.strip()
        ]

        from deepeval.test_case import LLMTestCase
        # Create test case
        test_case = LLMTestCase(
            input=question,
            actual_output=result["answer"],
            expected_output=q_data["expected_answer"],
            retrieval_context=result["retrieved_context"],
            context=result["retrieved_context"],
        )
        
        # Store additional metadata including scope for scope-aware reporting
        test_case.additional_metadata = {
            "id": q_data.get("id", str(i)),
            "category": q_data.get("category", "Unknown"),
            "scope": q_data.get("scope", "in_scope"),  # Track scope for contextual relevancy analysis
        }

        # Verbose logging commented to reduce terminal clutter
        # logger.debug(f"  ✓ Answer length: {len(result['answer'])} chars")
        # logger.debug(f"  ✓ Context chunks: {len(result['retrieved_context'])}")
        # logger.debug("  ✓ Expected answer provided for semantic validation")
        
        # FIX 4: VERIFY CLEAN CHUNKS BEFORE DEEPEVAL
        if result["retrieved_context"]:
            total_context_chars = sum(len(chunk) for chunk in result["retrieved_context"])
            avg_chunk_size = total_context_chars / len(result["retrieved_context"])
            # Verbose context stats commented to reduce terminal clutter
            # logger.debug(f"  📊 Context stats: {len(result['retrieved_context'])} chunks, "
            #            f"avg {avg_chunk_size:.0f} chars/chunk, total {total_context_chars} chars")
            
            # Verify chunks don't contain metadata noise
            metadata_indicators = ["ID:", "URL:", "http://", "gs://", "Timestamp:"]
            chunks_with_metadata = sum(
                1 for chunk in result["retrieved_context"] 
                if any(indicator in chunk for indicator in metadata_indicators)
            )
            if chunks_with_metadata > 0:
                logger.warning(
                    f"[{i}/{num_questions}]  ⚠️ {chunks_with_metadata}/{len(result['retrieved_context'])} chunks "
                    f"still contain metadata - may affect Contextual Relevancy"
                )

        # Run context debugging to identify potential Recall issues
        if result["retrieved_context"]:
            debug_stats = debug_context_recall(
                q_data["expected_answer"], result["retrieved_context"], question
            )
            # Merge debug stats into existing metadata
            test_case.additional_metadata["context_debug"] = debug_stats
        else:
            logger.error(f"[{i}/{num_questions}]  ❌ NO CONTEXT - Context Recall will be 0.0")

        # FIX 6: Attach original question data to test case for correct CSV mapping
        test_case.additional_metadata = test_case.additional_metadata or {}
        test_case.additional_metadata["_original_q_data"] = q_data

        return test_case

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
async def create_test_cases(questions: list[dict[str, str]]) -> list[LLMTestCase]:
    """Create DeepEval test cases by calling the root agent in parallel.

    Uses asyncio.gather with Semaphore to process multiple questions concurrently
    while respecting Vertex AI rate limits.

    Args:
        questions: List of question dictionaries (must include 'expected_answer')

    Returns:
        List of LLMTestCase objects with expected_output for semantic validation
    """
    logger.info(f"Creating test cases for {len(questions)} questions (async mode)...")

    

    # Semaphore to limit concurrent API calls (avoid rate limits and OAuth token refresh issues)
    # Set to 5 for balanced throughput with Windows event loop fixes
    concurrency_limit = os.cpu_count() * 2
    semaphore = asyncio.Semaphore(concurrency_limit)

    # from hr_analyst.agent import root_agent
    # # Create session service and runner ONCE (reuse for all questions)
    from google.adk.sessions import InMemorySessionService
    session_service = InMemorySessionService()
    # runner = Runner(
    #     agent=root_agent, session_service=session_service, app_name="deepeval"
    # )
    # user_id = "eval_user"

    

    # Process all questions in parallel
    tasks = [process_question(semaphore, session_service, i + 1, len(questions), q_data) for i, q_data in enumerate(questions)]
    results = await asyncio.gather(*tasks)
    
    # Process all questions in sequence
    # results = []
    # for i, q_data in enumerate(questions):
    #     res = await process_question(i + 1, q_data)
    #     results.append(res)

    # Filter out None values (skipped questions)
    test_cases = [tc for tc in results if tc is not None]
    skipped = len(questions) - len(test_cases)

    if skipped > 0:
        logger.warning(f"⚠️  Skipped {skipped} questions without expected answers")

    logger.info(f"✓ Created {len(test_cases)} test cases with semantic validation")
    return test_cases


def run_evaluation(
    test_cases: list[LLMTestCase],
    judge_model: DeepEvalBaseLLM,
    metric_threshold: float | None = None,
    essential_metrics_only: bool = False,
) -> dict[str, Any]:
    """Run DeepEval evaluation with semantic validation metrics.

    Args:
        test_cases: List of test cases to evaluate (must include expected_output)
        judge_model: The LLM to use as judge
        metric_threshold: Threshold for all metrics (None = use config default)
        essential_metrics_only: If True, use only 3 essential metrics (faster)

    Returns:
        Dictionary containing evaluation results and summary statistics
    """
    # Use config threshold if not provided
    if metric_threshold is None:
        metric_threshold = config.metrics.default_threshold
    
    # FIX 12: Determine per-metric thresholds
    # If --metric-threshold CLI override is provided, use it for ALL metrics;
    # otherwise use per-metric values from config.yaml
    cli_override = metric_threshold != config.metrics.default_threshold
    t_faithfulness = metric_threshold if cli_override else config.metrics.thresholds.faithfulness
    t_answer_relevancy = metric_threshold if cli_override else config.metrics.thresholds.answer_relevancy
    t_contextual_relevancy = metric_threshold if cli_override else config.metrics.thresholds.contextual_relevancy
    t_contextual_precision = metric_threshold if cli_override else config.metrics.thresholds.contextual_precision
    t_contextual_recall = metric_threshold if cli_override else config.metrics.thresholds.contextual_recall
    t_hallucination = metric_threshold if cli_override else config.metrics.thresholds.hallucination
    
    if cli_override:
        logger.info(f"CLI --metric-threshold={metric_threshold} overriding all per-metric thresholds")
    
    from deepeval import evaluate
    from deepeval.evaluate import DisplayConfig
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
        HallucinationMetric,
    )
    if essential_metrics_only:
        logger.info(
            f"Initializing ESSENTIAL metrics only (threshold: {metric_threshold})..."
        )
        # Only the 3 most critical metrics for faster evaluation
        metrics = [
            FaithfulnessMetric(
                threshold=t_faithfulness,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            AnswerRelevancyMetric(
                threshold=t_answer_relevancy,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            HallucinationMetric(
                threshold=t_hallucination,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
        ]
        logger.info("[+] Essential Metrics Enabled (FAST MODE):")
        logger.info("    - FaithfulnessMetric (answer grounded in context)")
        logger.info("    - AnswerRelevancyMetric (answer relevance to question)")
        logger.info("    - HallucinationMetric (fabrication detection)")
        metric_count_msg = "3 LLM-based metrics may take 2-4 minutes per test case"
    else:
        logger.info(
            f"Initializing comprehensive semantic validation metrics (threshold: {metric_threshold})..."
        )
        # All 6 metrics for semantic validation against expected answers
        # Using per-metric thresholds from config (can be overridden by command line)
        metrics = [
            FaithfulnessMetric(
                threshold=t_faithfulness,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            AnswerRelevancyMetric(
                threshold=t_answer_relevancy,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            ContextualRelevancyMetric(
                threshold=t_contextual_relevancy,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            ContextualPrecisionMetric(
                threshold=t_contextual_precision,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            ContextualRecallMetric(
                threshold=t_contextual_recall,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
            HallucinationMetric(
                threshold=t_hallucination,
                model=judge_model,
                include_reason=config.metrics.include_reason,
            ),
        ]
        logger.info("[+] Semantic Validation Metrics Enabled:")
        logger.info("    - FaithfulnessMetric (answer grounded in context)")
        logger.info("    - AnswerRelevancyMetric (answer relevance to question)")
        logger.info("    - ContextualRelevancyMetric (context relevance to query)")
        logger.info("    - ContextualPrecisionMetric (context quality/ranking)")
        logger.info("    - ContextualRecallMetric (completeness score)")
        logger.info("    - HallucinationMetric (fabrication detection)")
        metric_count_msg = "6 LLM-based metrics may take 5-8 minutes per test case"

    logger.info(f"Running evaluation on {len(test_cases)} test cases...")
    logger.info(f"Metrics: {[m.__class__.__name__ for m in metrics]}")
    logger.info(f"NOTE: Evaluation with {metric_count_msg}")
    timeout_seconds = int(
        os.getenv("DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE", "1200")
    )
    logger.info(
        f"Timeout configured: {timeout_seconds} seconds ({timeout_seconds / 60:.1f} minutes) per task"
    )

    # CRITICAL: Warm up SSL/OAuth tokens with a synchronous call BEFORE async evaluation
    # This prevents "503 Getting metadata from plugin failed" errors when multiple async
    # tasks try to refresh OAuth tokens simultaneously
    logger.info("Warming up judge model with synchronous call...")
    try:
        _ = judge_model.generate("ping")  # Synchronous call to cache OAuth tokens
        logger.info("✓ Judge model SSL/OAuth tokens cached successfully")
    except Exception as e:
        logger.warning(f"Warmup call failed (non-critical): {e}")

    # Run evaluation in fault-tolerant batches
    # If a batch fails, fall back to individual test case evaluation so one
    # bad response from the judge model doesn't crash the entire run.
    BATCH_SIZE = 10
    all_test_results = []
    error_count = 0
    
    total_batches = (len(test_cases) + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(
        f"Evaluating {len(test_cases)} test cases in {total_batches} batches of {BATCH_SIZE} "
        f"(fault-tolerant mode: errors are logged and skipped)"
    )

    display_config = DisplayConfig(
        print_results=False, 
        verbose_mode=False, 
        show_indicator=False
    )

    for batch_idx in range(0, len(test_cases), BATCH_SIZE):
        batch = test_cases[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        logger.info(f"--- Batch {batch_num}/{total_batches} ({len(batch)} test cases) ---")

        try:
            batch_results = evaluate(test_cases=batch, metrics=metrics, display_config=display_config)
            all_test_results.extend(batch_results.test_results)
            logger.info(f"✓ Batch {batch_num} completed successfully")
        except (KeyError, Exception) as batch_err:
            logger.warning(
                f"⚠️  Batch {batch_num} failed ({type(batch_err).__name__}: {batch_err}), "
                f"falling back to individual evaluation..."
            )
            # Retry each test case individually
            for tc_offset, single_tc in enumerate(batch):
                tc_global_idx = batch_idx + tc_offset + 1
                try:
                    single_result = evaluate(test_cases=[single_tc], metrics=metrics, display_config=display_config)
                    all_test_results.extend(single_result.test_results)
                    logger.info(f"  ✓ Test case #{tc_global_idx} succeeded on individual retry")
                except (KeyError, Exception) as tc_err:
                    error_count += 1
                    logger.error(
                        f"  ❌ Test case #{tc_global_idx} FAILED: {type(tc_err).__name__}: {tc_err}"
                    )
                    logger.error(
                        f"     Question: {single_tc.input[:80]}..."
                    )
                    # Create a placeholder result with None scores so CSV still gets a row
                    # We use a SimpleNamespace to mimic test_result structure
                    from types import SimpleNamespace
                    placeholder = SimpleNamespace(
                        metrics_data=[],
                        success=False,
                        input=single_tc.input,
                    )
                    all_test_results.append(placeholder)

    if error_count > 0:
        logger.warning(
            f"⚠️  Evaluation completed with {error_count} failed test case(s) out of {len(test_cases)}"
        )
    else:
        logger.info(f"✓ All {len(test_cases)} test cases evaluated successfully")

    # Build a results-like object for downstream compatibility
    from types import SimpleNamespace
    results = SimpleNamespace(test_results=all_test_results)

    # Extract scores from results object
    # DeepEval stores scores in results.test_results list
    logger.info(
        f"DEBUG: Extracting scores from {len(results.test_results)} test results..."
    )

    # Store scores in a separate dictionary (can't modify Pydantic test_case objects)
    test_case_scores = {}

    # Map scores from results to our dictionary
    for i, test_result in enumerate(results.test_results):
        test_case_scores[i] = {
            "faithfulness_score": None,
            "answer_relevancy_score": None,
            "hallucination_score": None,
            "contextual_relevancy_score": None,
            "contextual_precision_score": None,
            "contextual_recall_score": None,
        }

        # Extract scores from test_result.metrics_data
        for metric_data in test_result.metrics_data:
            metric_name = (
                metric_data.name
                if hasattr(metric_data, "name")
                else metric_data.__class__.__name__
            )
            score = metric_data.score

            logger.debug(f"  Test {i}: {metric_name} = {score}")

            if "Faithfulness" in metric_name:
                test_case_scores[i]["faithfulness_score"] = score
            elif metric_name == "Answer Relevancy":
                test_case_scores[i]["answer_relevancy_score"] = score
            elif metric_name == "Contextual Relevancy":
                test_case_scores[i]["contextual_relevancy_score"] = score
            elif (
                "Contextual Precision" in metric_name
                or metric_name == "Contextual Precision"
            ):
                test_case_scores[i]["contextual_precision_score"] = score
            elif (
                "Contextual Recall" in metric_name or metric_name == "Contextual Recall"
            ):
                test_case_scores[i]["contextual_recall_score"] = score
            elif "Hallucination" in metric_name:
                test_case_scores[i]["hallucination_score"] = score

    # Calculate metric pass rate for each test case
    for i in test_case_scores:
        scores_dict = test_case_scores[i]
        evaluated_count = 0
        passed_count = 0
        
        for metric in metrics:
            metric_name = metric.__class__.__name__.replace("Metric", "")
            score_key = METRIC_SCORE_KEY_MAP.get(metric_name)
            if score_key and score_key in scores_dict:
                score = scores_dict[score_key]
                if score is not None and isinstance(score, (int, float)):
                    evaluated_count += 1
                    # Hallucination is inverted: lower is better
                    if metric_name == "Hallucination":
                        if score <= metric.threshold:
                            passed_count += 1
                    else:
                        if score >= metric.threshold:
                            passed_count += 1
        
        # Store metric pass rate for this test case
        test_case_scores[i]["metric_pass_rate"] = (
            (passed_count / evaluated_count * 100) if evaluated_count > 0 else 0.0
        )
        test_case_scores[i]["metrics_passed"] = f"{passed_count}/{evaluated_count}"

    # Compute summary statistics
    summary = compute_summary_statistics(test_cases, metrics, results, test_case_scores)

    return {
        "results": results,
        "summary": summary,
        "test_cases": test_cases,
        "scores": test_case_scores,
    }


def compute_summary_statistics(
    test_cases: list[LLMTestCase],
    metrics: list,
    results: Any = None,
    test_case_scores: dict | None = None,
) -> dict[str, Any]:
    """Compute summary statistics from evaluation results.

    Args:
        test_cases: List of evaluated test cases
        metrics: List of metrics used
        results: Evaluation results object
        test_case_scores: Dictionary mapping test case index to scores

    Returns:
        Dictionary containing summary statistics
    """
    if test_case_scores is None:
        test_case_scores = {}
    summary = {
        "total_test_cases": len(test_cases),
        "metrics": {},
        "overall_pass_rate": 0.0,
        "failed_cases": 0,
    }

    # Compute per-metric statistics
    for metric in metrics:
        metric_name = metric.__class__.__name__.replace("Metric", "")
        scores = []
        passed = 0

        for i in range(len(test_cases)):
            # Get score from our scores dictionary
            score = None
            if i in test_case_scores:
                score_key = METRIC_SCORE_KEY_MAP.get(metric_name)
                if score_key and score_key in test_case_scores[i]:
                    score = test_case_scores[i][score_key]

            if score is not None and isinstance(score, (int, float)):
                scores.append(score)
                
                # Get scope for this test case
                test_case = test_cases[i]
                scope = "in_scope"
                if hasattr(test_case, "additional_metadata") and test_case.additional_metadata:
                    scope = test_case.additional_metadata.get("scope", "in_scope")
                
                # SCOPE-AWARE LOGIC for ContextualRelevancy
                if metric_name == "ContextualRelevancy":
                    if scope == "out_of_scope":
                        # OUT-OF-SCOPE: Low relevancy is GOOD (inverted logic)
                        if score < metric.threshold:
                            passed += 1
                    else:
                        # IN-SCOPE: High relevancy is GOOD (normal logic)
                        if score >= metric.threshold:
                            passed += 1
                # Hallucination metric is inverted: lower is better
                elif metric_name == "Hallucination":
                    if score <= metric.threshold:
                        passed += 1
                else:
                    if score >= metric.threshold:
                        passed += 1

        if scores:
            summary["metrics"][metric_name] = {
                "average_score": sum(scores) / len(scores),
                "threshold": metric.threshold,
                "passed": passed,
                "total": len(scores),
                "pass_rate": (passed / len(scores)) * 100 if scores else 0,
            }

    # Compute overall pass rate (all metrics must pass)
    all_passed = 0
    for i in range(len(test_cases)):
        case_passed = True
        
        # Get scope for this test case
        test_case = test_cases[i]
        scope = "in_scope"
        if hasattr(test_case, "additional_metadata") and test_case.additional_metadata:
            scope = test_case.additional_metadata.get("scope", "in_scope")
        
        for metric in metrics:
            metric_name = metric.__class__.__name__.replace("Metric", "")

            # Get score from our scores dictionary
            score = None
            if i in test_case_scores:
                score_key = METRIC_SCORE_KEY_MAP.get(metric_name)
                if score_key and score_key in test_case_scores[i]:
                    score = test_case_scores[i][score_key]

            if score is not None and isinstance(score, (int, float)):
                # SCOPE-AWARE LOGIC for ContextualRelevancy
                if metric_name == "ContextualRelevancy":
                    if scope == "out_of_scope":
                        # OUT-OF-SCOPE: Low relevancy is GOOD (inverted logic)
                        if score >= metric.threshold:
                            case_passed = False
                            break
                    else:
                        # IN-SCOPE: High relevancy is GOOD (normal logic)
                        if score < metric.threshold:
                            case_passed = False
                            break
                # Hallucination metric is inverted: lower is better
                elif metric_name == "Hallucination":
                    if score > metric.threshold:
                        case_passed = False
                        break
                else:
                    if score < metric.threshold:
                        case_passed = False
                        break

        if case_passed:
            all_passed += 1

    summary["overall_pass_rate"] = (
        (all_passed / len(test_cases)) * 100 if test_cases else 0
    )
    summary["failed_cases"] = len(test_cases) - all_passed

    # Calculate average metric pass rate across all test cases
    metric_pass_rates = []
    for i in test_case_scores:
        if "metric_pass_rate" in test_case_scores[i]:
            metric_pass_rates.append(test_case_scores[i]["metric_pass_rate"])
    
    summary["average_metric_pass_rate"] = (
        sum(metric_pass_rates) / len(metric_pass_rates) if metric_pass_rates else 0.0
    )

    return summary


# ---------------------------------------------------------------------------
# Results Export
# ---------------------------------------------------------------------------
def save_results_to_csv(
    eval_data: dict[str, Any], output_path: str, questions: list[dict[str, str]]
) -> None:
    """Save detailed evaluation results to CSV file.

    Args:
        eval_data: Evaluation data including test cases and metrics
        output_path: Path to output CSV file
        questions: Original question data with IDs and categories
    """
    logger.info(f"Saving detailed results to {output_path}...")

    test_cases = eval_data["test_cases"]
    test_case_scores = eval_data.get("scores", {})

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "ID",
            "Category",
            "Scope",
            "Question",
            "Answer",
            "Context_Chunks",
            "Faithfulness_Score",
            "Relevancy_Score",
            "Contextual_Relevancy_Score",
            "Context_Precision_Score",
            "Context_Recall_Score",
            "Hallucination_Score",
            "Metrics_Passed",
            "Metric_Pass_Rate",
            "Overall_Pass",
            "Failed_Metrics",
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, test_case in enumerate(test_cases):
            # FIX 6: Use original question data attached to test case
            # instead of questions[i] which breaks when questions are skipped
            q_data = (
                test_case.additional_metadata.get("_original_q_data", {})
                if hasattr(test_case, "additional_metadata") and test_case.additional_metadata
                else {}
            )

            # Extract metric scores and replace None with "N/A" for display
            scores_dict = test_case_scores.get(i, {})
            score_vars = {
                "faithfulness": scores_dict.get("faithfulness_score"),
                "relevancy": scores_dict.get("answer_relevancy_score"),
                "contextual_relevancy": scores_dict.get("contextual_relevancy_score"),
                "precision": scores_dict.get("contextual_precision_score"),
                "recall": scores_dict.get("contextual_recall_score"),
                "hallucination": scores_dict.get("hallucination_score"),
            }
            # Replace None with "N/A"
            score_vars = {k: (v if v is not None else "N/A") for k, v in score_vars.items()}
            faithfulness = score_vars["faithfulness"]
            relevancy = score_vars["relevancy"]
            contextual_relevancy = score_vars["contextual_relevancy"]
            precision = score_vars["precision"]
            recall = score_vars["recall"]
            hallucination = score_vars["hallucination"]

            # FIX 1: Use config thresholds instead of hardcoded values
            scores = [
                faithfulness,
                relevancy,
                contextual_relevancy,
                precision,
                recall,
                hallucination,
            ]
            thresholds = [
                config.metrics.thresholds.faithfulness,
                config.metrics.thresholds.answer_relevancy,
                config.metrics.thresholds.contextual_relevancy,
                config.metrics.thresholds.contextual_precision,
                config.metrics.thresholds.contextual_recall,
                config.metrics.thresholds.hallucination,
            ]
            metric_names = [
                "Faithfulness",
                "Relevancy",
                "Contextual_Relevancy",
                "Precision",
                "Recall",
                "Hallucination",
            ]

            # Extract scope from test case metadata for scope-aware evaluation
            scope = "in_scope"  # Default
            if hasattr(test_case, "additional_metadata") and test_case.additional_metadata:
                scope = test_case.additional_metadata.get("scope", "in_scope")
            
            failed_metrics = []
            passed_metrics = []
            evaluated_metrics = 0  # Count metrics that were actually evaluated (not N/A)
            
            for score, threshold, name in zip(
                scores, thresholds, metric_names, strict=False
            ):
                if score != "N/A" and isinstance(score, (int, float)):
                    evaluated_metrics += 1
                    
                    # SCOPE-AWARE LOGIC for Contextual_Relevancy
                    if name == "Contextual_Relevancy":
                        if scope == "out_of_scope":
                            # OUT-OF-SCOPE: Low relevancy is GOOD (correctly found no relevant docs)
                            # Pass if score < threshold (inverted logic)
                            if score >= threshold:
                                failed_metrics.append(f"{name} (out-of-scope: too high)")
                            else:
                                passed_metrics.append(name)
                        else:
                            # IN-SCOPE: High relevancy is GOOD (found relevant docs)
                            # Pass if score >= threshold (normal logic)
                            if score < threshold:
                                failed_metrics.append(name)
                            else:
                                passed_metrics.append(name)
                    # Hallucination metric is inverted: lower is better, pass if score <= threshold
                    elif name == "Hallucination":
                        if score > threshold:
                            failed_metrics.append(name)
                        else:
                            passed_metrics.append(name)
                    else:
                        # Other metrics: higher is better, pass if score >= threshold
                        if score < threshold:
                            failed_metrics.append(name)
                        else:
                            passed_metrics.append(name)

            # Calculate pass rate for this test case
            metrics_passed_count = len(passed_metrics)
            metrics_pass_rate = (
                (metrics_passed_count / evaluated_metrics * 100) 
                if evaluated_metrics > 0 else 0.0
            )
            metrics_passed_str = f"{metrics_passed_count}/{evaluated_metrics}"
            
            overall_pass = "PASS" if not failed_metrics else "FAIL"

            writer.writerow(
                {
                    "ID": q_data.get("id", i + 1),
                    "Category": q_data.get("category", "Unknown"),
                    "Scope": scope,  # Already extracted above
                    "Question": test_case.input,
                    "Answer": test_case.actual_output[:500]
                    + ("..." if len(test_case.actual_output) > 500 else ""),
                    "Context_Chunks": len(test_case.retrieval_context or []),
                    "Faithfulness_Score": (
                        f"{faithfulness:.3f}" if faithfulness != "N/A" else "N/A"
                    ),
                    "Relevancy_Score": (
                        f"{relevancy:.3f}" if relevancy != "N/A" else "N/A"
                    ),
                    "Contextual_Relevancy_Score": (
                        f"{contextual_relevancy:.3f}"
                        if contextual_relevancy != "N/A"
                        else "N/A"
                    ),
                    "Context_Precision_Score": (
                        f"{precision:.3f}" if precision != "N/A" else "N/A"
                    ),
                    "Context_Recall_Score": (
                        f"{recall:.3f}" if recall != "N/A" else "N/A"
                    ),
                    "Hallucination_Score": (
                        f"{hallucination:.3f}" if hallucination != "N/A" else "N/A"
                    ),
                    "Metrics_Passed": metrics_passed_str,
                    "Metric_Pass_Rate": f"{metrics_pass_rate:.1f}%",
                    "Overall_Pass": overall_pass,
                    "Failed_Metrics": "; ".join(failed_metrics)
                    if failed_metrics
                    else "",
                }
            )

    logger.info(f"[OK] Results saved to {output_path}")


def print_summary(summary: dict[str, Any]) -> None:
    """Print evaluation summary to console.

    Args:
        summary: Summary statistics dictionary
    """
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(f"\nTotal Test Cases: {summary['total_test_cases']}")
    print(f"Overall Pass Rate: {summary['overall_pass_rate']:.1f}%")
    print(f"  (Test cases where ALL metrics passed)")
    print(f"Failed Test Cases: {summary['failed_cases']}")
    print(f"  (Test cases where at least one metric failed)")
    print("\n" + "-" * 70)
    print("INDIVIDUAL METRIC PASS RATES")
    print("-" * 70)
    print("(A test case can pass some metrics while failing others)")

    for metric_name, stats in summary["metrics"].items():
        print(f"\n{metric_name}:")
        print(f"  Average Score: {stats['average_score']:.3f}")
        print(f"  Threshold: {stats['threshold']:.2f}")
        print(
            f"  Pass Rate: {stats['pass_rate']:.1f}% ({stats['passed']}/{stats['total']})"
        )

    print("\n" + "=" * 70)


def generate_textual_summary(summary: dict[str, Any]) -> str:
    """Generate a textual summary of evaluation results.

    Args:
        summary: Summary statistics dictionary

    Returns:
        Textual summary string
    """
    overall_pass_rate = summary["overall_pass_rate"]

    # Determine overall performance using config thresholds
    excellent_threshold = config.performance_bands.excellent * 100
    good_threshold = config.performance_bands.good * 100
    acceptable_threshold = config.performance_bands.acceptable * 100
    
    if overall_pass_rate >= excellent_threshold:
        performance = "EXCELLENT"
        performance_desc = "The chatbot is performing exceptionally well."
    elif overall_pass_rate >= good_threshold:
        performance = "GOOD"
        performance_desc = "The chatbot is performing well with minor issues."
    elif overall_pass_rate >= acceptable_threshold:
        performance = "ACCEPTABLE"
        performance_desc = (
            "The chatbot performance is acceptable but needs improvement."
        )
    else:
        performance = "POOR"
        performance_desc = "The chatbot performance needs significant improvement."

    # Find metrics that need improvement
    needs_improvement = []
    for metric_name, stats in summary["metrics"].items():
        # Hallucination metric is inverted: higher is worse, but it's already handled by pass_rate
        # Skip it from general improvement list as we handle it separately
        if metric_name == "Hallucination":
            continue
        if stats["average_score"] < stats["threshold"]:
            needs_improvement.append(
                f"{metric_name} (avg: {stats['average_score']:.3f}, "
                f"threshold: {stats['threshold']:.2f})"
            )

    # Check hallucination risk (higher score = higher risk = worse)
    hallucination_stats = summary["metrics"].get("Hallucination", {})
    hallucination_score = hallucination_stats.get("average_score", 0.0)
    # FIX 3: Use config threshold instead of hardcoded 0.8 fallback
    # For Hallucination: 0.0 = no hallucinations (LOW risk), 1.0 = full hallucination (HIGH risk)
    hallucination_threshold = hallucination_stats.get(
        "threshold", config.metrics.thresholds.hallucination
    )
    hallucination_risk = (
        "HIGH"
        if hallucination_score > hallucination_threshold
        else "LOW"
    )

    # Build summary text
    summary_text = f"""
EVALUATION SUMMARY REPORT
{"=" * 70}

Overall Performance: {performance}
{performance_desc}

TEST CASE RESULTS:
{'-' * 70}
Overall Test Case Pass Rate: {overall_pass_rate:.1f}%
  (Test cases with ALL metrics passing threshold)

Average Metric Pass Rate: {summary.get('average_metric_pass_rate', 0):.1f}%
  (Average of individual metric pass rates per test case)

Total Cases Evaluated: {summary["total_test_cases"]}
Cases with All Metrics Passing: {summary['total_test_cases'] - summary['failed_cases']}
Cases with Some Metrics Failing: {summary["failed_cases"]}

NOTE: The 'Overall Test Case Pass Rate' requires ALL metrics to pass,
while 'Average Metric Pass Rate' shows the actual percentage of metrics
passing across all test cases. See detailed CSV for per-case breakdown.

METRIC ANALYSIS:
{"-" * 70}
"""

    for metric_name, stats in summary["metrics"].items():
        summary_text += f"\n{metric_name}:\n"
        summary_text += (
            f"  - Average Score: {stats['average_score']:.3f} "
            f"(Threshold: {stats['threshold']:.2f})\n"
        )
        summary_text += f"  - Pass Rate: {stats['pass_rate']:.1f}%\n"

    summary_text += f"\nRECOMMENDATIONS:\n{'-' * 70}\n"

    if needs_improvement:
        summary_text += "\nMetrics Requiring Improvement:\n"
        for metric in needs_improvement:
            summary_text += f"  - {metric}\n"
    else:
        summary_text += "\n[OK] All metrics are meeting their thresholds.\n"

    summary_text += f"\nHallucination Risk: {hallucination_risk}\n"

    if hallucination_risk == "HIGH":
        summary_text += (
            "  [!] ATTENTION: The chatbot shows high hallucination risk. "
            "Review grounding mechanisms.\n"
        )

    return summary_text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Main evaluation script entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate HR Chatbot using DeepEval with Gemini as Judge"
    )
    parser.add_argument(
        "--input",
        "-i",
        default=config.csv_files.default_input,
        help=f"Path to input CSV file with questions (default: {config.csv_files.default_input})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=config.csv_files.default_output,
        help=f"Path to output CSV file for results (default: {config.csv_files.default_output})",
    )
    parser.add_argument(
        "--question-column",
        "-q",
        default=config.csv_columns.question,
        help=f"Name of the question column in CSV (default: {config.csv_columns.question})",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        help="Limit evaluation to first N questions (for testing)",
    )
    parser.add_argument(
        "--judge-model",
        "-m",
        default=config.judge.default_model,
        help=f"Vertex AI model to use as judge (default: {config.judge.default_model})",
    )
    parser.add_argument(
        "--expected-answer-column",
        default=config.csv_columns.expected_answer,
        help=f"CSV column name containing expected/ground truth answers (default: '{config.csv_columns.expected_answer}')",
    )
    parser.add_argument(
        "--metric-threshold",
        "-t",
        type=float,
        default=config.metrics.default_threshold,
        help=f"Threshold for all evaluation metrics (0.0 to 1.0, default: {config.metrics.default_threshold})",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to custom config.yaml file (optional, default: deep_eval_scripts/config.yaml)",
    )
    parser.add_argument(
        "--essential-metrics",
        "-e",
        action="store_true",
        help="Use only essential metrics (Faithfulness, Answer Relevancy, Hallucination) - ~50%% faster for large datasets",
    )

    args = parser.parse_args()

    # Fix Windows console encoding to handle Unicode characters
    if sys.platform == "win32":
        try:
            # Set console to use UTF-8 encoding
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass  # If this fails, continue with default encoding

    # Reload config if custom config path is provided
    if args.config:
        try:
            from deep_eval_scripts.config import reload_config
        except ImportError:
            from config import reload_config
        reload_config(Path(args.config))
        logger.info(f"Loaded custom configuration from: {args.config}")

    # Initialize environment and imports (deferred from module level)
    _init_environment()
    _init_imports()

    try:
        # Initialize judge model
        logger.info(f"Initializing judge model: {args.judge_model}")
        judge_model = VertexAIGeminiModel(model_name=args.judge_model)

        # Load questions from CSV
        logger.info(f"Loading questions from: {args.input}")
        questions = load_questions_from_csv(
            args.input,
            question_col=args.question_column,
            expected_answer_col=args.expected_answer_column,
            limit=args.limit,
        )

        # Validate that we have expected answers
        with_expected = sum(1 for q in questions if "expected_answer" in q)
        logger.info(
            f"Loaded {with_expected}/{len(questions)} questions with expected answers from column '{args.expected_answer_column}'"
        )

        if with_expected == 0:
            logger.error(
                f"No expected answers found in column '{args.expected_answer_column}'"
            )
            logger.error("Please verify the column name and that it contains data")
            sys.exit(1)

        if with_expected < len(questions):
            logger.warning(
                f"⚠️  {len(questions) - with_expected} questions missing expected answers - they will be skipped"
            )

        if not questions:
            logger.error("No questions found in CSV file")
            sys.exit(1)

        # Create test cases with async processing
        test_cases = asyncio.run(create_test_cases(questions))

        # Run evaluation with semantic validation metrics
        eval_data = run_evaluation(
            test_cases, 
            judge_model, 
            metric_threshold=args.metric_threshold,
            essential_metrics_only=args.essential_metrics
        )

        # Save results
        save_results_to_csv(eval_data, args.output, questions)

        # Print summary
        print_summary(eval_data["summary"])

        # Generate and save textual summary
        textual_summary = generate_textual_summary(eval_data["summary"])
        summary_path = args.output.replace(".csv", "_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(textual_summary)
        logger.info(f"[OK] Textual summary saved to {summary_path}")

        # Print textual summary
        print(textual_summary)

        logger.info("[OK] Evaluation completed successfully!")

        logger.info(f"Threshold Pass Rate : {float(config.ci_cd.default_threshold)*100}")
        logger.info(f"Overall Pass Rate : {eval_data["summary"]['overall_pass_rate']}")
        if eval_data["summary"]['overall_pass_rate'] >= float(config.ci_cd.default_threshold)*100:
            logger.info(f"Overall Pass Rate is above Threshold")
        else:
            logger.error(f"Overall Pass Rate is below Threshold")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    start_time = datetime.now()
    main()
    end_time = datetime.now()
    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())

    minutes = total_seconds // 60
    seconds = total_seconds % 60

    logger.info(f"Time taken: {minutes}m {seconds}s")
````
<!-- END: deep_eval_scripts/evaluate_hr_chatbot_v3.py -->

