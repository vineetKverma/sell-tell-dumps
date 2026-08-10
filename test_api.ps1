$base = "http://localhost:8000/api/v1"
function Send-Json($uri, $obj) {
  try { return @{ code=200; body=(Invoke-RestMethod -Method Post -Uri $uri -Body ($obj|ConvertTo-Json -Depth 6) -ContentType "application/json") } }
  catch { $c=0; if ($_.Exception.Response) { $c=$_.Exception.Response.StatusCode.value__ }; return @{ code=$c; body=$_.ErrorDetails.Message } }
}
function Check($n,$ok,$d) { if ($ok) { Write-Host "PASS  $n" -ForegroundColor Green } else { Write-Host "FAIL  $n -> $d" -ForegroundColor Red } }

# --- A: uncovered planned topic must BLOCK commit (409) ---
$a = Send-Json "$base/notes/stage" @{ event_type="On-site visit"; executive_summary="Acme."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=3; executive_summary="Re-sign."; discussed=$true})
  planned_topics=@("Contract / agreement renewal","Pricing"); campaign_type="standard_sales" }
$ac = Send-Json "$base/notes/commit" @{ session_id=$a.body.session_id; confirmed=$true; agent_mode="implicit"; campaign_type="standard_sales" }
Check "A  incomplete coverage blocked" ($ac.code -eq 409) "got $($ac.code)"

# --- B: campaign-illegal event type + code must be REJECTED (422) ---
$b = Send-Json "$base/notes/stage" @{ event_type="On-site visit"; executive_summary="Renewals."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=1; executive_summary="Quote."; discussed=$true})
  planned_topics=@("Contract / agreement renewal"); campaign_type="renewals" }
Check "B  illegal event type + code rejected" ($b.code -eq 422) "got $($b.code)"

# --- C1: full coverage must COMMIT ---
$c1 = Send-Json "$base/notes/stage" @{ event_type="On-site visit"; executive_summary="Acme."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=3; executive_summary="Re-sign."; discussed=$true},
           @{topic="Pricing"; disposition_code=8; executive_summary="10% high."; discussed=$true})
  planned_topics=@("Contract / agreement renewal","Pricing"); campaign_type="standard_sales" }
$c1c = Send-Json "$base/notes/commit" @{ session_id=$c1.body.session_id; confirmed=$true; agent_mode="implicit"; campaign_type="standard_sales" }
Check "C1 full coverage commits" ($c1c.code -eq 200 -and $c1c.body.crm_record_id) "got $($c1c.code)"

# --- C2: renewals with LEGAL values must stage ---
$c2 = Send-Json "$base/notes/stage" @{ event_type="Phone Call"; executive_summary="Renewals."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=8; executive_summary="Pricing concern."; discussed=$true})
  planned_topics=@("Contract / agreement renewal"); campaign_type="renewals" }
Check "C2 legal renewals payload accepted" ($c2.code -eq 200) "got $($c2.code)"

# --- C4: guided escape hatch (needs_manual_review, no code) must COMMIT ---
$c4 = Send-Json "$base/notes/stage" @{ event_type="Phone Call"; executive_summary="Ambiguous."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; executive_summary="Unclear after 3 attempts."; discussed=$true; needs_manual_review=$true})
  planned_topics=@("Contract / agreement renewal"); campaign_type="renewals" }
$c4c = Send-Json "$base/notes/commit" @{ session_id=$c4.body.session_id; confirmed=$true; agent_mode="guided"; campaign_type="renewals" }
Check "C4 needs_manual_review commits" ($c4c.code -eq 200 -and $c4c.body.crm_record_id) "got $($c4c.code)"

# --- C3 (revised): skip is honoured only AFTER the reminder ---
$c3a = Send-Json "$base/notes/stage" @{ event_type="On-site visit"; executive_summary="Acme."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=3; executive_summary="Re-sign."; discussed=$true})
  planned_topics=@("Contract / agreement renewal","Pricing"); campaign_type="standard_sales" }
Check "C3a first stage reports the gap" ($c3a.body.missing_topics -contains "Pricing") "got $($c3a.body.missing_topics)"

# rep answers "I skipped it" -> re-stage against the previous session id
$c3b = Send-Json "$base/notes/stage?previous_session_id=$($c3a.body.session_id)" @{
  event_type="On-site visit"; executive_summary="Acme."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=3; executive_summary="Re-sign."; discussed=$true},
           @{topic="Pricing"; executive_summary="Ran out of time."; discussed=$false})
  planned_topics=@("Contract / agreement renewal","Pricing"); campaign_type="standard_sales" }
Check "C3b re-stage accepts the skip" ($c3b.body.all_topics_covered -eq $true) "got $($c3b.body.missing_topics)"
$c3c = Send-Json "$base/notes/commit" @{ session_id=$c3b.body.session_id; confirmed=$true; agent_mode="implicit"; campaign_type="standard_sales" }
Check "C3c commits after real skip" ($c3c.code -eq 200 -and $c3c.body.crm_record_id) "got $($c3c.code)"

# --- C5 (new): model cannot skip on the rep's behalf on the first call ---
$c5 = Send-Json "$base/notes/stage" @{ event_type="On-site visit"; executive_summary="Acme."; raw_transcript_backup="..."
  topics=@(@{topic="Contract / agreement renewal"; disposition_code=3; executive_summary="Re-sign."; discussed=$true},
           @{topic="Pricing"; executive_summary="Rep did not get to pricing due to time constraints."; discussed=$false})
  planned_topics=@("Contract / agreement renewal","Pricing"); campaign_type="standard_sales" }
Check "C5 self-skip on first stage does NOT count as coverage" ($c5.body.missing_topics -contains "Pricing") "got $($c5.body.missing_topics)"



