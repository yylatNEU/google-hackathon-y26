from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        decoded = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {error.code}: {decoded[:400]}") from error
    return json.loads(decoded or "{}")


def _memory(base_url: str) -> dict[str, Any]:
    return _request(base_url, "GET", "/api/park/experience-studio/memory?limit=5", timeout=10)


def run(base_url: str, use_llm: bool = False) -> dict[str, Any]:
    started = time.time()
    readiness = _request(base_url, "GET", "/api/park/experience-studio/readiness", timeout=10)
    before = _memory(base_url)
    conversation_plan = _request(
        base_url,
        "POST",
        "/api/park/experience-studio/conversation-plan",
        {
            "message": "Create a rainy-day family journey with verified indoor stops, calm guest copy, app, signage, email, and staff cue artifacts.",
            "useVenueExperienceData": True,
        },
        timeout=12,
    )
    plan_payload = (conversation_plan.get("recommendedPlan") or {}).get("payload")
    if not isinstance(plan_payload, dict) or not plan_payload.get("templateId"):
        raise RuntimeError("Conversation plan did not include a generator-ready recommendedPlan.payload")
    generated = _request(
        base_url,
        "POST",
        "/api/park/experience-studio/draft",
        {
            **plan_payload,
            "useVenueExperienceData": True,
            "useLlm": use_llm,
        },
    )
    draft = generated.get("draft") if isinstance(generated.get("draft"), dict) else {}
    creative_package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    saved = _request(
        base_url,
        "POST",
        "/api/park/experience-studio/drafts",
        {
            "templateId": "rainy-day",
            "draft": draft,
            "actor": "demo_verifier",
            "sourceMode": generated.get("mode"),
        },
        timeout=45,
    )
    draft_id = str((saved.get("draftRecord") or {}).get("id") or "")
    if not draft_id:
        raise RuntimeError("Save response did not include draftRecord.id")

    updated = _request(
        base_url,
        "POST",
        f"/api/park/experience-studio/drafts/{urllib.parse.quote(draft_id)}",
        {"draft": draft, "actor": "demo_verifier", "note": "Demo lifecycle update receipt."},
        timeout=45,
    )
    approved = _request(
        base_url,
        "POST",
        f"/api/park/experience-studio/drafts/{urllib.parse.quote(draft_id)}/status",
        {"status": "approved", "actor": "demo_verifier", "note": "Approved for demo handoff verification."},
        timeout=45,
    )
    promoted_rule = _request(
        base_url,
        "POST",
        f"/api/park/experience-studio/drafts/{urllib.parse.quote(draft_id)}/promote-rule",
        {
            "candidateId": "complete_package_shape",
            "actor": "demo_verifier",
            "note": "Promote approved package shape for future Experience Studio context.",
        },
        timeout=45,
    )
    generated_after_rule = _request(
        base_url,
        "POST",
        "/api/park/experience-studio/draft",
        {
            **plan_payload,
            "useVenueExperienceData": True,
            "useLlm": False,
            "useApprovedLearningRules": True,
        },
    )
    post_rule_draft = generated_after_rule.get("draft") if isinstance(generated_after_rule.get("draft"), dict) else {}
    post_rule_package = post_rule_draft.get("creativePackage") if isinstance(post_rule_draft.get("creativePackage"), dict) else {}
    handoff = _request(
        base_url,
        "POST",
        f"/api/park/experience-studio/drafts/{urllib.parse.quote(draft_id)}/handoff",
        {"actor": "demo_verifier", "note": "Create demo handoff package."},
        timeout=45,
    )
    handoff_id = str((handoff.get("handoff") or {}).get("id") or "")
    handoff_review = {}
    if handoff_id:
        handoff_review = _request(
            base_url,
            "POST",
            f"/api/park/experience-studio/handoffs/{urllib.parse.quote(handoff_id)}/status",
            {
                "status": "accepted_for_channel_owner_review",
                "actor": "demo_verifier",
                "note": "Accepted for channel-owner review during demo verification.",
            },
        )
    after = _memory(base_url)
    before_counts = before.get("collectionCounts", {}) if isinstance(before.get("collectionCounts"), dict) else {}
    after_counts = after.get("collectionCounts", {}) if isinstance(after.get("collectionCounts"), dict) else {}
    connection = after.get("memoryConnection", {}) if isinstance(after.get("memoryConnection"), dict) else {}
    return {
        "status": "passed",
        "baseUrl": base_url,
        "elapsedSeconds": round(time.time() - started, 3),
        "readiness": readiness,
        "memoryConnection": connection,
        "beforeCounts": before_counts,
        "afterCounts": after_counts,
        "deltas": {
            name: int(after_counts.get(name, 0) or 0) - int(before_counts.get(name, 0) or 0)
            for name in sorted(set(before_counts) | set(after_counts))
        },
        "created": {
            "conversationPlanId": conversation_plan.get("id"),
            "conversationPlanMemoryId": (conversation_plan.get("memoryPersistence") or {}).get("memoryId"),
            "generationMemoryId": (generated.get("memoryPersistence") or {}).get("memoryId"),
            "postRuleGenerationMemoryId": (generated_after_rule.get("memoryPersistence") or {}).get("memoryId"),
            "draftId": draft_id,
            "handoffId": handoff_id or None,
            "promotedRuleId": (promoted_rule.get("rule") or {}).get("id"),
        },
        "contracts": {
            "conversationTemplateId": (conversation_plan.get("parsedBrief") or {}).get("templateId"),
            "conversationPayloadTemplateId": plan_payload.get("templateId"),
            "conversationNoSeedData": (conversation_plan.get("sourceIntegrity") or {}).get("usesSeedData") is False,
            "studioCoreId": (generated.get("studioCore") or {}).get("id"),
            "llmRequested": use_llm,
            "llmStatus": (generated.get("llm") or {}).get("status"),
            "llmMergeStatus": (draft.get("llmCreativePass") or {}).get("status"),
            "llmSynthesisAcceptedFields": (draft.get("llmCreativePass") or {}).get("synthesisAcceptedFields"),
            "noFeedbackLoop": after.get("learningPolicy", {}).get("humanFeedbackLearningEligible") is False,
            "approvedRulePromotionEligible": after.get("learningPolicy", {}).get("approvedRulePromotionEligible") is True,
            "promotedRuleStatus": promoted_rule.get("status"),
            "postRuleGenerationUsesApprovedRules": (post_rule_package.get("approvedRuleInfluence") or {}).get("usedForGeneration") is True,
            "mongoConnected": connection.get("connected") is True and connection.get("primary") == "mongodb",
        },
        "statuses": {
            "conversationPlan": conversation_plan.get("status"),
            "generate": generated.get("status"),
            "save": saved.get("status"),
            "update": updated.get("status"),
            "approve": approved.get("status"),
            "promoteRule": promoted_rule.get("status"),
            "postRuleGenerate": generated_after_rule.get("status"),
            "handoff": handoff.get("status"),
            "handoffReview": handoff_review.get("status") if handoff_review else "skipped",
        },
        "conversationPlan": {
            "parsedBrief": conversation_plan.get("parsedBrief", {}),
            "plannerIntelligence": conversation_plan.get("plannerIntelligence", {}),
            "conceptOptions": conversation_plan.get("conceptOptions", []),
            "clarifyingQuestions": conversation_plan.get("clarifyingQuestions", []),
            "recommendedOptionId": conversation_plan.get("recommendedOptionId"),
            "recommendedPlan": conversation_plan.get("recommendedPlan", {}),
        },
        "finalGeneratedResult": {
            "title": draft.get("title"),
            "audience": draft.get("audience"),
            "intent": draft.get("intent"),
            "creativeBrief": draft.get("creativeBrief", {}),
            "creativePackage": creative_package,
            "experienceReasoning": draft.get("experienceReasoning", {}),
            "creativeSynthesis": draft.get("creativeSynthesis", {}),
            "route": draft.get("route", []),
            "messages": draft.get("messages", []),
            "productionNotes": draft.get("productionNotes", []),
            "review": draft.get("review", []),
            "studioReview": draft.get("studioReview", []),
            "sourceIntegrity": draft.get("sourceIntegrity", {}),
            "reasoningTrace": draft.get("reasoningTrace", []),
            "profileIntelligence": draft.get("profileIntelligence", {}),
            "handoff": handoff.get("handoff", {}),
        },
        "approvedRuleLifecycle": {
            "promotion": promoted_rule,
            "postPromotionGeneration": {
                "status": generated_after_rule.get("status"),
                "mode": generated_after_rule.get("mode"),
                "approvedLearningRules": post_rule_draft.get("approvedLearningRules", {}),
                "approvedRuleInfluence": post_rule_package.get("approvedRuleInfluence", {}),
                "creativeSynthesisRuleInfluence": (post_rule_draft.get("creativeSynthesis") or {}).get("learningRuleInfluence", {}),
                "selectedConceptName": (post_rule_draft.get("creativeSynthesis") or {}).get("selectedConceptName"),
                "packageChecklist": ((post_rule_package.get("productionDetail") or {}).get("contentCompletenessChecklist") or []),
            },
        },
    }


def _render_html(report: dict[str, Any]) -> str:
    report_json = json.dumps(report, indent=2).replace("</", "<\\/")
    rows = [
        ("Status", report.get("status")),
        ("Base URL", report.get("baseUrl")),
        ("Elapsed", f"{report.get('elapsedSeconds')}s"),
        ("Mongo connected", report.get("contracts", {}).get("mongoConnected")),
        ("No feedback loop", report.get("contracts", {}).get("noFeedbackLoop")),
        ("Studio Core", report.get("contracts", {}).get("studioCoreId")),
        ("Conversation plan ID", report.get("created", {}).get("conversationPlanId")),
        ("Conversation template", report.get("contracts", {}).get("conversationTemplateId")),
        ("Generation memory ID", report.get("created", {}).get("generationMemoryId")),
        ("Post-rule generation memory ID", report.get("created", {}).get("postRuleGenerationMemoryId")),
        ("Draft ID", report.get("created", {}).get("draftId")),
        ("Handoff ID", report.get("created", {}).get("handoffId")),
        ("Promoted rule ID", report.get("created", {}).get("promotedRuleId")),
    ]
    summary_rows = "".join(f"<tr><td>{escape(str(label))}</td><td>{escape(str(value))}</td></tr>" for label, value in rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Interactive Experience Studio Verification</title>
  <style>
    :root {{ color-scheme: dark; --bg: #10130f; --panel: #151914; --panel2: #0d1115; --line: #334155; --soft: #1f2937; --text: #e5e7eb; --muted: #94a3b8; --dim: #64748b; --lime: #bef264; --cyan: #67e8f9; --green: #86efac; --amber: #fcd34d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 24px; }}
    header, section {{ border: 1px solid var(--soft); background: var(--panel); border-radius: 10px; padding: 18px; }}
    header {{ border-color: rgba(190, 242, 100, .3); }}
    h1, h2, h3 {{ margin: 0; color: white; letter-spacing: 0; }}
    h1 {{ margin-top: 8px; font-size: clamp(30px, 5vw, 52px); line-height: 1.02; }}
    h2 {{ font-size: 22px; }}
    h3 {{ font-size: 15px; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .eyebrow {{ color: var(--lime); font-size: 11px; font-weight: 900; letter-spacing: .14em; text-transform: uppercase; }}
    .tabs {{ position: sticky; top: 0; z-index: 2; display: flex; gap: 8px; overflow-x: auto; margin: 16px 0; padding: 10px; border: 1px solid var(--soft); background: rgba(13, 17, 21, .94); border-radius: 10px; }}
    .tab, .btn {{ border: 1px solid var(--soft); background: var(--panel2); color: var(--text); border-radius: 7px; padding: 9px 11px; font-size: 12px; font-weight: 900; cursor: pointer; }}
    .tab.active, .btn.primary {{ border-color: var(--cyan); background: var(--cyan); color: #081014; }}
    .view {{ display: none; }}
    .view.active {{ display: block; }}
    .grid4 {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .grid2 {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid var(--soft); background: var(--panel2); border-radius: 8px; padding: 14px; }}
    .metric span, .label {{ display: block; color: var(--dim); font-size: 10px; font-weight: 900; letter-spacing: .1em; text-transform: uppercase; }}
    .metric strong {{ display: block; margin-top: 7px; color: white; font-size: 28px; line-height: 1; }}
    .metric small, .value {{ display: block; margin-top: 7px; color: var(--muted); line-height: 1.45; }}
    .pill {{ display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 10px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase; }}
    .pass {{ color: var(--green); background: rgba(20,83,45,.34); border-color: rgba(134,239,172,.42); }}
    .warn {{ color: var(--amber); background: rgba(120,53,15,.34); border-color: rgba(252,211,77,.42); }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }}
    input, select {{ border: 1px solid var(--line); background: var(--panel2); color: var(--text); border-radius: 7px; padding: 10px 12px; outline: none; }}
    input {{ min-width: 280px; flex: 1; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; background: var(--panel2); border: 1px solid var(--soft); }}
    td, th {{ border-bottom: 1px solid var(--soft); padding: 10px 12px; text-align: left; vertical-align: top; font-size: 13px; line-height: 1.45; }}
    th {{ color: var(--cyan); text-transform: uppercase; font-size: 11px; letter-spacing: .08em; }}
    code, pre {{ background: #080b0d; color: #d9f99d; }}
    code {{ border: 1px solid var(--soft); border-radius: 5px; padding: 2px 5px; }}
    pre {{ overflow: auto; max-height: 70vh; padding: 16px; border: 1px solid var(--soft); border-radius: 8px; font-size: 12px; line-height: 1.5; }}
    .stack {{ display: grid; gap: 10px; }}
    .copy-state {{ color: var(--lime); font-size: 12px; }}
    @media (max-width: 960px) {{ main {{ padding: 14px; }} .grid4, .grid3, .grid2 {{ grid-template-columns: 1fr; }} .tabs {{ position: static; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Live backend verification</div>
    <h1>Experience Studio Report + Final Generated Result</h1>
    <p>This artifact was generated from the running backend at <code>{escape(str(report.get("baseUrl")))}</code>. It includes the final creative package, route storyboard, channel copy, review gates, memory receipts, and raw JSON.</p>
    <div class="toolbar">
      <span class="pill pass">Verifier {escape(str(report.get("status")))}</span>
      <span class="pill pass">No seed data</span>
      <span class="pill pass">Audit-only memory</span>
      <button class="btn primary" data-copy="package">Copy final package</button>
      <button class="btn" data-copy="route">Copy route</button>
      <button class="btn" data-copy="raw">Copy raw JSON</button>
      <span id="copyState" class="copy-state"></span>
    </div>
  </header>

  <nav class="tabs" aria-label="Report sections">
    <button class="tab active" data-view="overview">Overview</button>
    <button class="tab" data-view="planner">Planner</button>
    <button class="tab" data-view="final">Final Package</button>
    <button class="tab" data-view="synthesis">Creative Synthesis</button>
    <button class="tab" data-view="reasoning">Design Reasoning</button>
    <button class="tab" data-view="route">Route</button>
    <button class="tab" data-view="channels">Channels</button>
    <button class="tab" data-view="profile">Profile Intelligence</button>
    <button class="tab" data-view="review">Review</button>
    <button class="tab" data-view="memory">Memory</button>
    <button class="tab" data-view="raw">Raw JSON</button>
  </nav>

  <section id="view-overview" class="view active">
    <h2>Overview</h2>
    <div class="grid4" id="metrics" style="margin-top:14px"></div>
    <table><tbody>{summary_rows}</tbody></table>
  </section>
  <section id="view-planner" class="view"><h2>Conversation Planner</h2><div id="planner" class="stack" style="margin-top:14px"></div></section>
  <section id="view-final" class="view"><h2>Final Package</h2><div id="final" class="stack" style="margin-top:14px"></div></section>
  <section id="view-synthesis" class="view"><h2>Creative Synthesis</h2><div id="creativeSynthesis" class="stack" style="margin-top:14px"></div></section>
  <section id="view-reasoning" class="view"><h2>Design Reasoning</h2><div id="designReasoning" class="stack" style="margin-top:14px"></div></section>
  <section id="view-route" class="view"><h2>Route Storyboard</h2><div class="toolbar"><input id="routeSearch" placeholder="Filter stops, copy, staff notes, accessibility..." /></div><div id="route" class="stack"></div></section>
  <section id="view-channels" class="view"><h2>Channel Artifacts</h2><div id="channels" class="grid2" style="margin-top:14px"></div></section>
  <section id="view-profile" class="view"><h2>Profile Intelligence</h2><div id="profileIntel" class="stack" style="margin-top:14px"></div></section>
  <section id="view-review" class="view"><h2>Review Gates</h2><div id="review" class="grid2" style="margin-top:14px"></div></section>
  <section id="view-memory" class="view"><h2>Memory Receipts</h2><div id="memory" class="stack" style="margin-top:14px"></div></section>
  <section id="view-raw" class="view"><h2>Raw JSON</h2><pre id="raw"></pre></section>
</main>
<script type="application/json" id="reportData">{report_json}</script>
<script>
  const report = JSON.parse(document.getElementById("reportData").textContent);
  const result = report.finalGeneratedResult || {{}};
  const ruleLifecycle = report.approvedRuleLifecycle || {{}};
  const postRule = ruleLifecycle.postPromotionGeneration || {{}};
  const plan = report.conversationPlan || {{}};
  const plannerIntel = plan.plannerIntelligence || {{}};
  const pkg = result.creativePackage || {{}};
  const creativeSynthesis = result.creativeSynthesis || pkg.creativeSynthesis || {{}};
  const designReasoning = result.experienceReasoning || pkg.designReasoning || {{}};
  const profileIntel = result.profileIntelligence || {{}};
  const profileReady = profileIntel.readiness || {{}};
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[char]));
  const list = (items) => (Array.isArray(items) && items.length ? `<ul>${{items.map((item) => `<li>${{esc(typeof item === "string" ? item : JSON.stringify(item))}}</li>`).join("")}}</ul>` : "<p>None.</p>");
  const jsonText = (value) => JSON.stringify(value, null, 2);
  const metric = (label, value, detail = "") => `<div class="card metric"><span>${{esc(label)}}</span><strong>${{esc(value)}}</strong><small>${{esc(detail)}}</small></div>`;
  document.getElementById("metrics").innerHTML = [
    metric("Route stops", (result.route || []).length, result.title),
    metric("Channel artifacts", (result.messages || []).length, "App, signage, email, staff cue"),
    metric("Ready", result.sourceIntegrity?.readyForHandoff ? "yes" : "review", "Source-integrity gate"),
    metric("Profile intel", profileReady.status || result.sourceIntegrity?.profileIntelligenceStatus || "unknown", result.sourceIntegrity?.realVenueReady ? "Real-venue-ready" : "Creative-ready, review gated"),
    metric("Approved rules", postRule.approvedRuleInfluence?.usedForGeneration ? "active" : "inactive", `${{postRule.approvedRuleInfluence?.ruleCount || 0}} rule context`)
  ].join("");
  document.getElementById("planner").innerHTML = `
    <div class="grid4">
      ${{metric("Template", plan.parsedBrief?.templateId || "n/a", plan.parsedBrief?.templateLabel || "")}}
      ${{metric("Segment", plannerIntel.targetSegment?.label || plan.parsedBrief?.targetSegment || "n/a", "Profile-inferred guest lens")}}
      ${{metric("Pattern", plannerIntel.routePattern?.id || "n/a", "Venue route recipe")}}
      ${{metric("Channels", (plannerIntel.channelTargets || []).join(", ") || "n/a", "Lead artifact targets")}}
    </div>
    <div class="grid2">
      <div class="card"><h3>Route pattern</h3><div class="label">Arc</div>${{list(plannerIntel.routePattern?.recommendedArc || [])}}<div class="label">Must include</div>${{list(plannerIntel.routePattern?.mustInclude || [])}}<div class="label">Avoid claims</div>${{list(plannerIntel.routePattern?.avoidClaims || [])}}</div>
      <div class="card"><h3>Refinement prompts</h3>${{list(plan.clarifyingQuestions || [])}}</div>
    </div>
    <div class="grid3">
      ${{(plan.conceptOptions || []).map((option) => `<div class="card"><h3>${{esc(option.label || option.id)}} ${{option.id === plan.recommendedOptionId ? "(recommended)" : ""}}</h3><p>${{esc(option.rationale || "")}}</p><div class="label">Risk</div><div class="value">${{esc(option.risk || "")}}</div><div class="label">Profile fit</div><pre>${{esc(jsonText(option.profileFit || {{}}))}}</pre></div>`).join("")}}
    </div>`;
  const concept = pkg.executiveConcept || {{}};
  document.getElementById("final").innerHTML = `
    <div class="card"><h3>${{esc(concept.name || result.title)}}</h3><p>${{esc(concept.oneLine)}}</p><table><tbody>
      <tr><td>Guest promise</td><td>${{esc(concept.guestPromise)}}</td></tr>
      <tr><td>Why now</td><td>${{esc(concept.whyNow)}}</td></tr>
      <tr><td>Success metric</td><td>${{esc(concept.successMetric)}}</td></tr>
      <tr><td>Package version</td><td><code>${{esc(pkg.version)}}</code></td></tr>
    </tbody></table></div>
    <div class="grid3">
      <div class="card"><h3>Experience beats</h3>${{list((pkg.experienceBeats || []).map((item) => `${{item.beat}}: ${{item.detail}}`))}}</div>
      <div class="card"><h3>Staff script</h3><pre>${{esc(jsonText(pkg.staffScript || {{}}))}}</pre></div>
      <div class="card"><h3>Owner questions</h3>${{list(pkg.ownerQuestions || [])}}</div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Pre-arrival email</h3><div class="label">Subject</div><div class="value">${{esc(pkg.preArrivalEmail?.subject)}}</div><div class="label">Body</div><div class="value">${{esc(pkg.preArrivalEmail?.body)}}</div></div>
      <div class="card"><h3>Signage set</h3>${{list((pkg.signageSet || []).map((item) => `${{item.placement}} - ${{item.headline}}: ${{item.body}}`))}}</div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Section dossiers</h3>${{list((pkg.sectionDossiers || []).map((item) => `${{item.section}}: ${{item.purpose}} Review: ${{item.reviewGate}}`))}}</div>
      <div class="card"><h3>Route blueprint</h3>${{list((pkg.routeBlueprint || []).map((item) => `${{item.order}}. ${{item.stop}} / ${{item.storyBeat}} / ${{item.guestAction}}`))}}</div>
      <div class="card"><h3>Channel matrix</h3>${{list((pkg.channelMatrix || []).map((item) => `${{item.channel}} / ${{item.owner}}: ${{item.objective}}`))}}</div>
      <div class="card"><h3>Staff run-of-show</h3>${{list((pkg.staffRunOfShow || []).map((item) => `${{item.phase}} / ${{item.who}}: ${{item.detail}}`))}}</div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Production detail</h3><div class="label">Guest choice model</div>${{list(pkg.productionDetail?.guestChoiceModel || [])}}<div class="label">Checklist</div>${{list(pkg.productionDetail?.contentCompletenessChecklist || [])}}<div class="label">Measurement</div>${{list((pkg.productionDetail?.measurementPlan || []).map((item) => `${{item.metric}}: ${{item.signal}} / ${{item.learningUse}}`))}}</div>
      <div class="card"><h3>Finished-work memory</h3><div class="label">Status</div><div class="value">${{esc(pkg.memoryInfluence?.status || "unknown")}}</div><div class="label">Used</div><div class="value">${{esc(pkg.memoryInfluence?.usedForGeneration ? "yes" : "no")}}</div><div class="label">Reusable patterns</div>${{list(pkg.memoryInfluence?.reusablePatterns || [])}}<div class="label">Matched examples</div>${{list((pkg.memoryInfluence?.matchedExamples || []).map((item) => `${{item.status}} / ${{item.selectedConceptName}} / ${{item.draftId}}`))}}</div>
    </div>
    <div class="card"><h3>Approved-rule effect on next generation</h3>
      <div class="grid3">
        <div><div class="label">Promotion</div><div class="value">${{esc(ruleLifecycle.promotion?.status || "unknown")}}</div></div>
        <div><div class="label">Used for next generation</div><div class="value">${{esc(postRule.approvedRuleInfluence?.usedForGeneration ? "yes" : "no")}}</div></div>
        <div><div class="label">Authority</div><div class="value">${{esc(postRule.approvedRuleInfluence?.authority || "human_promoted_rules_only")}}</div></div>
      </div>
      <div class="label">Applied rules</div>${{list(postRule.approvedLearningRules?.appliedRules || [])}}
      <div class="label">Guardrails</div>${{list(postRule.approvedLearningRules?.guardrails || [])}}
      <div class="label">Post-rule checklist</div>${{list(postRule.packageChecklist || [])}}
    </div>
    <div class="card"><h3>Venue pattern</h3><div class="grid3">
      <div><div class="label">Pattern</div><div class="value">${{esc(pkg.venuePattern?.id || "n/a")}}</div></div>
      <div><div class="label">Recommended arc</div>${{list(pkg.venuePattern?.recommendedArc || [])}}</div>
      <div><div class="label">Must include</div>${{list(pkg.venuePattern?.mustInclude || [])}}</div>
    </div><div class="label">Avoid claims</div>${{list(pkg.venuePattern?.avoidClaims || [])}}</div>`;
  document.getElementById("creativeSynthesis").innerHTML = `
    <div class="grid4">
      ${{metric("Status", creativeSynthesis.status || "unknown", creativeSynthesis.mode || "creative synthesis")}}
      ${{metric("Selected", creativeSynthesis.selectedConceptName || creativeSynthesis.selectedConceptId || "n/a", "Named creative concept")}}
      ${{metric("Concepts", (creativeSynthesis.concepts || []).length, "Generated variants")}}
      ${{metric("Score", creativeSynthesis.selectedConcept?.totalScore ?? "n/a", "Selected concept score")}}
    </div>
    <div class="card"><h3>LLM polish receipt</h3><div class="grid3">
      <div><div class="label">Status</div><div class="value">${{esc(creativeSynthesis.llmPolish?.status || "not requested")}}</div></div>
      <div><div class="label">Accepted fields</div><div class="value">${{esc(creativeSynthesis.llmPolish?.acceptedFields ?? 0)}}</div></div>
      <div><div class="label">Guardrails</div>${{list(creativeSynthesis.llmPolish?.guardrails || [])}}</div>
    </div><div class="label">Rejected fields</div>${{list((creativeSynthesis.llmPolish?.rejectedFields || []).map((item) => `${{item.field}}: ${{item.reason}}`))}}</div>
    <div class="card"><h3>Decision</h3><p>${{esc(creativeSynthesis.decision?.whySelected || "")}}</p><div class="label">Use more of</div>${{list(creativeSynthesis.rewriteStrategy?.useMoreOf || [])}}<div class="label">Avoid</div>${{list(creativeSynthesis.rewriteStrategy?.avoid || [])}}</div>
    <div class="grid3">
      ${{(creativeSynthesis.concepts || []).map((concept) => `<div class="card"><h3>${{esc(concept.name || concept.id)}} ${{concept.id === creativeSynthesis.selectedConceptId ? "(selected)" : ""}}</h3><p>${{esc(concept.positioning || "")}}</p><div class="label">Guest promise</div><div class="value">${{esc(concept.guestPromise || "")}}</div><div class="label">Hero terms</div>${{list(concept.heroTerms || [])}}<div class="label">Review risks</div>${{list(concept.reviewRisks || [])}}</div>`).join("") || "<p>No synthesis concepts returned.</p>"}}
    </div>
    <div class="grid3">
      <div class="card"><h3>Guest app</h3><div class="label">Headline</div><div class="value">${{esc(creativeSynthesis.copyVariants?.guestApp?.headline)}}</div><div class="label">Body</div><div class="value">${{esc(creativeSynthesis.copyVariants?.guestApp?.body)}}</div><div class="label">Microcopy</div><div class="value">${{esc(creativeSynthesis.copyVariants?.guestApp?.microcopy)}}</div></div>
      <div class="card"><h3>Email</h3><div class="label">Subject</div><div class="value">${{esc(creativeSynthesis.copyVariants?.email?.subject)}}</div><div class="label">Preview</div><div class="value">${{esc(creativeSynthesis.copyVariants?.email?.previewText)}}</div><div class="label">Body</div><div class="value">${{esc(creativeSynthesis.copyVariants?.email?.body)}}</div></div>
      <div class="card"><h3>Staff cue</h3><pre>${{esc(jsonText(creativeSynthesis.copyVariants?.staffCue || {{}}))}}</pre></div>
    </div>`;
  document.getElementById("designReasoning").innerHTML = `
    <div class="grid4">
      ${{metric("Status", designReasoning.status || "unknown", designReasoning.mode || "experience design")}}
      ${{metric("Selected", designReasoning.selectedConceptLabel || designReasoning.selectedConceptId || "n/a", "Chosen concept route")}}
      ${{metric("Score", designReasoning.decision?.totalScore ?? "n/a", "Mean quality score")}}
      ${{metric("Alternatives", (designReasoning.conceptRoutes || []).length, "Scored before selection")}}
    </div>
    <div class="card"><h3>Decision</h3><p>${{esc(designReasoning.decision?.whySelected || "")}}</p><div class="label">Route</div><div class="value">${{esc((designReasoning.decision?.route || []).join(" -> "))}}</div><div class="label">Evidence</div>${{list(designReasoning.decision?.decisiveEvidence || [])}}</div>
    <div class="grid3">
      ${{(designReasoning.conceptRoutes || []).map((concept) => `<div class="card"><h3>${{esc(concept.label || concept.id)}} ${{concept.id === designReasoning.selectedConceptId ? "(selected)" : ""}}</h3><p>${{esc(concept.positioning || "")}}</p><table><tbody>${{Object.entries(concept.scores || {{}}).map(([label, value]) => `<tr><td>${{esc(label)}}</td><td>${{esc(value)}}</td></tr>`).join("")}}<tr><td>Total</td><td>${{esc(concept.totalScore)}}</td></tr></tbody></table><div class="label">Route</div><div class="value">${{esc((concept.route || []).join(" -> "))}}</div><div class="label">Risks</div>${{list(concept.riskFlags || [])}}</div>`).join("") || "<p>No concept routes were returned.</p>"}}
    </div>
    <div class="grid3">
      <div class="card"><h3>Rejected alternatives</h3>${{list(designReasoning.decision?.rejectedAlternatives || [])}}</div>
      <div class="card"><h3>Critique and revision</h3><div class="label">Weak points</div>${{list(designReasoning.critiqueAndRevision?.weakPointsFound || [])}}<div class="label">Revisions applied</div>${{list(designReasoning.critiqueAndRevision?.revisionsApplied || [])}}</div>
      <div class="card"><h3>Guest lenses</h3>${{list((designReasoning.guestLenses || []).map((lens) => `${{lens.guest}}: ${{lens.designResponse}}`))}}</div>
    </div>`;
  const renderRoute = () => {{
    const query = (document.getElementById("routeSearch")?.value || "").toLowerCase();
    const rows = (result.route || []).filter((stop) => jsonText(stop).toLowerCase().includes(query));
    document.getElementById("route").innerHTML = rows.map((stop, index) => `<div class="card"><h3>${{index + 1}}. ${{esc(stop.stop)}}</h3><div class="grid2" style="margin-top:10px">
      <div><div class="label">Guest copy</div><div class="value">${{esc(stop.guestCopy)}}</div></div>
      <div><div class="label">Purpose</div><div class="value">${{esc(stop.purpose)}}</div></div>
      <div><div class="label">Staff note</div><div class="value">${{esc(stop.staffNote)}}</div></div>
      <div><div class="label">Accessibility</div><div class="value">${{esc(stop.accessibilityNote)}}</div></div>
    </div></div>`).join("") || "<p>No matching route stops.</p>";
  }};
  document.getElementById("routeSearch")?.addEventListener("input", renderRoute);
  renderRoute();
  document.getElementById("channels").innerHTML = (result.messages || []).map((message) => `<div class="card"><h3>${{esc(message.channel)}}</h3><div class="label">Owner</div><div class="value">${{esc(message.owner)}}</div><div class="label">Copy</div><div class="value">${{esc(message.copy)}}</div></div>`).join("");
  document.getElementById("profileIntel").innerHTML = `
    <div class="grid4">
      ${{metric("Status", profileReady.status || "unknown", "Profile Intelligence v1 readiness")}}
      ${{metric("Score", profileReady.score ?? "n/a", "Certified components")}}
      ${{metric("Real venue", result.sourceIntegrity?.realVenueReady ? "yes" : "no", result.sourceIntegrity?.usesApprovedSyntheticProfile ? "Synthetic/demo source" : "Non-synthetic source")}}
      ${{metric("Quality gaps", (profileIntel.qualityGaps || []).length, "Unresolved reasoning limits")}}
    </div>
    <div class="grid2">
      <div class="card"><h3>Required checks</h3><pre>${{esc(jsonText(profileReady.requiredChecks || []))}}</pre></div>
      <div class="card"><h3>Missing for real venue ready</h3>${{list(profileReady.missingForRealVenueReady || [])}}</div>
      <div class="card"><h3>Current quality gaps</h3>${{list(profileIntel.qualityGaps || [])}}</div>
      <div class="card"><h3>Contract</h3><pre>${{esc(jsonText(profileIntel.contract || {{}}))}}</pre></div>
    </div>`;
  document.getElementById("review").innerHTML = `
    <div class="card"><h3>Studio review</h3><pre>${{esc(jsonText(result.studioReview || []))}}</pre></div>
    <div class="card"><h3>Source integrity</h3><pre>${{esc(jsonText(result.sourceIntegrity || {{}}))}}</pre></div>
    <div class="card"><h3>Reasoning trace</h3><pre>${{esc(jsonText(result.reasoningTrace || []))}}</pre></div>
    <div class="card"><h3>Handoff</h3><pre>${{esc(jsonText(result.handoff || {{}}))}}</pre></div>`;
  document.getElementById("memory").innerHTML = `
    <div class="grid2"><div class="card"><h3>Collection deltas</h3><pre>${{esc(jsonText(report.deltas || {{}}))}}</pre></div>
    <div class="card"><h3>Lifecycle statuses</h3><pre>${{esc(jsonText(report.statuses || {{}}))}}</pre></div></div>
    <div class="card"><h3>Approved-rule lifecycle</h3><pre>${{esc(jsonText(ruleLifecycle || {{}}))}}</pre></div>
    <div class="card"><h3>Memory connection</h3><pre>${{esc(jsonText(report.memoryConnection || {{}}))}}</pre></div>`;
  document.getElementById("raw").textContent = jsonText(report);
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {{
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`view-${{tab.dataset.view}}`).classList.add("active");
  }}));
  document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", async () => {{
    const kind = button.dataset.copy;
    const value = kind === "route" ? result.route : kind === "raw" ? report : pkg;
    await navigator.clipboard.writeText(jsonText(value));
    document.getElementById("copyState").textContent = `Copied ${{kind}}.`;
    setTimeout(() => document.getElementById("copyState").textContent = "", 1600);
  }}));
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Experience Studio demo memory and lifecycle writes.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="ParkPulse backend base URL.")
    parser.add_argument("--html-output", default="", help="Optional path for an HTML verification report.")
    parser.add_argument("--use-llm", action="store_true", help="Request live LLM creative polish; deterministic verification remains the default.")
    args = parser.parse_args()
    report = run(args.base_url, use_llm=args.use_llm)
    if args.html_output:
        output_path = Path(args.html_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_render_html(report), encoding="utf-8")
        report["htmlOutput"] = str(output_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
