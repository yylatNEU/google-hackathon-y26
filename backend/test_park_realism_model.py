import asyncio
import json
from copy import deepcopy

from park_simulation import park_simulation
from parkpulse_api import (
    get_industrial_dossier,
    get_industrial_dossier_packet,
    get_industrial_dossiers,
    get_park_case_brief,
    get_park_cases,
    get_park_live_summary,
    score_industrial_dossier_quality,
)
from synthetic_park_runner import find_synthetic_example, injection_plan_for_example


def run(coro):
    return asyncio.run(coro)


def test_park_state_has_realistic_guest_system_and_temporal_models():
    run(park_simulation.reset_demo())
    state = run(park_simulation.get_state())
    conflicts = state["actionConflictSimulation"]["conflicts"]

    assert len(state["guestSegments"]) >= 5
    assert state["externalSystems"]["pendingWrites"] >= 1
    assert state["temporalConsequences"]["mode"] == "multi_step_operating_day_projection"
    assert [row["minute"] for row in state["temporalConsequences"]["timeline"]] == [0, 5, 10, 20, 35]
    assert state["physicalDynamics"]["mode"] == "physical_guest_staff_service_dynamics"
    assert state["physicalMap"]["lastDynamics"]["physicalConstraints"]
    assert state["industrialDossiers"]["mode"] == "industrial_operating_case_dossiers"
    assert state["industrialDossiers"]["summary"]["caseCount"] >= 7
    assert state["industrialDossiers"]["summary"]["domainCoverageCount"] >= 7
    assert state["industrialDossiers"]["summary"]["coverageGapCount"] == 0
    assert not state["industrialDossiers"]["portfolioCoverage"]["coverageGaps"]
    assert state["industrialDossiers"]["portfolioOperatingModel"]["mode"] == "industrial_portfolio_operating_model"
    assert state["industrialDossiers"]["portfolioOperatingModel"]["assetInventory"]["zones"] >= 5
    assert state["industrialDossiers"]["portfolioOperatingModel"]["spatialNetwork"]["pathCount"] >= 5
    assert state["industrialDossiers"]["portfolioOperatingModel"]["operatingDomains"]
    assert state["industrialDossiers"]["portfolioOperatingModel"]["receiverSurface"]
    assert state["industrialDossiers"]["portfolioOperatingModel"]["coverageReadiness"]["domainCoverageCount"] >= 7
    assert state["industrialDossiers"]["portfolioRiskRanking"]["mode"] == "industrial_portfolio_risk_ranking"
    assert len(state["industrialDossiers"]["portfolioRiskRanking"]["rankingRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["portfolioRiskRanking"]["topPriorityCaseId"]
    assert state["industrialDossiers"]["portfolioRiskRanking"]["operatingQueue"]
    assert state["industrialDossiers"]["portfolioRiskRanking"]["rankingRows"][0]["rank"] == 1
    assert state["industrialDossiers"]["productionEvidenceGapRegister"]["mode"] == "industrial_production_evidence_gap_register"
    assert state["industrialDossiers"]["productionEvidenceGapRegister"]["productionReady"] is False
    assert len(state["industrialDossiers"]["productionEvidenceGapRegister"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["productionEvidenceGapRegister"]["feedReadinessRows"]
    assert state["industrialDossiers"]["productionEvidenceGapRegister"]["promotionGate"]["productionReady"] is False
    assert state["industrialDossiers"]["fieldReplayValidationHarness"]["mode"] == "industrial_field_replay_validation_harness"
    assert state["industrialDossiers"]["fieldReplayValidationHarness"]["fieldValidated"] is False
    assert len(state["industrialDossiers"]["fieldReplayValidationHarness"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldReplayValidationHarness"]["summary"]["requiredReplayRunCount"] >= state["industrialDossiers"]["summary"]["caseCount"] * 60
    assert state["industrialDossiers"]["fieldReplayValidationHarness"]["portfolioReplayProtocol"]
    assert state["industrialDossiers"]["capacityCertificationLedger"]["mode"] == "industrial_capacity_certification_ledger"
    assert len(state["industrialDossiers"]["capacityCertificationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["capacityCertificationLedger"]["summary"]["caseCount"] == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["capacityCertificationLedger"]["releaseRules"]
    assert state["industrialDossiers"]["slaEscalationClock"]["mode"] == "industrial_sla_escalation_clock"
    assert len(state["industrialDossiers"]["slaEscalationClock"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["slaEscalationClock"]["summary"]["waitingCount"] >= 1
    assert state["industrialDossiers"]["slaEscalationClock"]["portfolioEscalationRules"]
    assert state["industrialDossiers"]["receiverExecutionContractLedger"]["mode"] == "industrial_receiver_execution_contract_ledger"
    assert len(state["industrialDossiers"]["receiverExecutionContractLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["receiverExecutionContractLedger"]["summary"]["contractCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["receiverExecutionContractLedger"]["contractRules"]
    assert state["industrialDossiers"]["externalSystemExecutionEvidence"]["mode"] == "industrial_external_system_execution_evidence"
    assert len(state["industrialDossiers"]["externalSystemExecutionEvidence"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["externalSystemExecutionEvidence"]["summary"]["preparedPayloadCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["externalSystemExecutionEvidence"]["executionRules"]
    assert state["industrialDossiers"]["industrialDossierCompletenessAudit"]["mode"] == "industrial_dossier_completeness_audit"
    assert len(state["industrialDossiers"]["industrialDossierCompletenessAudit"]["auditRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialDossierCompletenessAudit"]["summary"]["completeProofStackCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialDossierCompletenessAudit"]["auditRules"]
    assert state["industrialDossiers"]["liveEvidenceDriftMonitor"]["mode"] == "industrial_live_evidence_drift_monitor"
    assert len(state["industrialDossiers"]["liveEvidenceDriftMonitor"]["driftRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["liveEvidenceDriftMonitor"]["summary"]["maxDriftScore"] >= 0
    assert state["industrialDossiers"]["liveEvidenceDriftMonitor"]["driftRules"]
    assert state["industrialDossiers"]["observedOutcomeCalibrationLedger"]["mode"] == "industrial_observed_outcome_calibration_ledger"
    assert len(state["industrialDossiers"]["observedOutcomeCalibrationLedger"]["calibrationRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["observedOutcomeCalibrationLedger"]["summary"]["maxVarianceScore"] >= 0
    assert state["industrialDossiers"]["observedOutcomeCalibrationLedger"]["calibrationRules"]
    assert state["industrialDossiers"]["varianceRootCauseLedger"]["mode"] == "industrial_variance_root_cause_ledger"
    assert len(state["industrialDossiers"]["varianceRootCauseLedger"]["rootCauseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["varianceRootCauseLedger"]["summary"]["criticalCauseCount"] >= 0
    assert state["industrialDossiers"]["varianceRootCauseLedger"]["rootCauseRules"]
    assert state["industrialDossiers"]["industrialReviewDispositionLedger"]["mode"] == "industrial_review_disposition_ledger"
    assert len(state["industrialDossiers"]["industrialReviewDispositionLedger"]["dispositionRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialReviewDispositionLedger"]["summary"]["holdCount"] >= 0
    assert state["industrialDossiers"]["industrialReviewDispositionLedger"]["dispositionRules"]
    assert state["industrialDossiers"]["industrialAuditExportManifest"]["mode"] == "industrial_audit_export_manifest"
    assert len(state["industrialDossiers"]["industrialAuditExportManifest"]["packageRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialAuditExportManifest"]["summary"]["manifestHashCount"] == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialAuditExportManifest"]["manifestRules"]
    assert state["industrialDossiers"]["dataLineageCertificationLedger"]["mode"] == "industrial_data_lineage_certification_ledger"
    assert len(state["industrialDossiers"]["dataLineageCertificationLedger"]["certificationRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["dataLineageCertificationLedger"]["summary"]["sourceSystemCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["dataLineageCertificationLedger"]["lineageRules"]
    assert state["industrialDossiers"]["policyRiskControlLedger"]["mode"] == "industrial_policy_risk_control_ledger"
    assert len(state["industrialDossiers"]["policyRiskControlLedger"]["controlRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["policyRiskControlLedger"]["summary"]["sensitiveCaseCount"] >= 1
    assert state["industrialDossiers"]["policyRiskControlLedger"]["controlRules"]
    assert state["industrialDossiers"]["caseWorkOrderExecutionLedger"]["mode"] == "industrial_case_work_order_execution_ledger"
    assert len(state["industrialDossiers"]["caseWorkOrderExecutionLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["caseWorkOrderExecutionLedger"]["summary"]["workOrderCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["caseWorkOrderExecutionLedger"]["workOrderRules"]
    assert state["industrialDossiers"]["fieldReceiptReconciliationLedger"]["mode"] == "industrial_field_receipt_reconciliation_ledger"
    assert len(state["industrialDossiers"]["fieldReceiptReconciliationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldReceiptReconciliationLedger"]["summary"]["receiptRowCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldReceiptReconciliationLedger"]["reconciliationRules"]
    assert state["industrialDossiers"]["releaseBoardExceptionLedger"]["mode"] == "industrial_release_board_exception_ledger"
    assert len(state["industrialDossiers"]["releaseBoardExceptionLedger"]["exceptionRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["releaseBoardExceptionLedger"]["summary"]["holdCount"] >= 0
    assert state["industrialDossiers"]["releaseBoardExceptionLedger"]["exceptionRules"]
    assert state["industrialDossiers"]["scenarioCoverageCertificationLedger"]["mode"] == "industrial_scenario_coverage_certification_ledger"
    assert len(state["industrialDossiers"]["scenarioCoverageCertificationLedger"]["certificationRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["scenarioCoverageCertificationLedger"]["summary"]["requiredFamilyCount"] >= 8
    assert state["industrialDossiers"]["scenarioCoverageCertificationLedger"]["coverageRules"]
    assert state["industrialDossiers"]["operatorCompetencyEvaluationLedger"]["mode"] == "industrial_operator_competency_evaluation_ledger"
    assert len(state["industrialDossiers"]["operatorCompetencyEvaluationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["operatorCompetencyEvaluationLedger"]["summary"]["evaluationTaskCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["operatorCompetencyEvaluationLedger"]["evaluationRules"]
    assert state["industrialDossiers"]["causalEpisodeTrainingLedger"]["mode"] == "industrial_causal_episode_training_ledger"
    assert len(state["industrialDossiers"]["causalEpisodeTrainingLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["causalEpisodeTrainingLedger"]["summary"]["episodeFrameCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["causalEpisodeTrainingLedger"]["episodeRules"]
    assert state["industrialDossiers"]["simulationValidityCalibrationLedger"]["mode"] == "industrial_simulation_validity_calibration_ledger"
    assert len(state["industrialDossiers"]["simulationValidityCalibrationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["simulationValidityCalibrationLedger"]["summary"]["assumptionCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["simulationValidityCalibrationLedger"]["validityRules"]
    assert state["industrialDossiers"]["fieldObservationProtocolLedger"]["mode"] == "industrial_field_observation_protocol_ledger"
    assert len(state["industrialDossiers"]["fieldObservationProtocolLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldObservationProtocolLedger"]["summary"]["stationCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldObservationProtocolLedger"]["protocolRules"]
    assert state["industrialDossiers"]["fieldEvidenceCaptureLedger"]["mode"] == "industrial_field_evidence_capture_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceCaptureLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceCaptureLedger"]["summary"]["formCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceCaptureLedger"]["captureRules"]
    assert state["industrialDossiers"]["fieldEvidenceSampleLedger"]["mode"] == "industrial_field_evidence_sample_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceSampleLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceSampleLedger"]["summary"]["recordCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceSampleLedger"]["validationRules"]
    assert state["industrialDossiers"]["fieldEvidenceAdjudicationLedger"]["mode"] == "industrial_field_evidence_adjudication_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceAdjudicationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceAdjudicationLedger"]["summary"]["metricAdjudicationCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceAdjudicationLedger"]["adjudicationRules"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationLedger"]["mode"] == "industrial_field_evidence_remediation_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceRemediationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationLedger"]["summary"]["remediationActionCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationLedger"]["remediationRules"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationExecutionLedger"]["mode"] == "industrial_field_evidence_remediation_execution_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceRemediationExecutionLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationExecutionLedger"]["summary"]["executionReceiptCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceRemediationExecutionLedger"]["executionRules"]
    assert state["industrialDossiers"]["fieldEvidenceReleaseClearanceLedger"]["mode"] == "industrial_field_evidence_release_clearance_ledger"
    assert len(state["industrialDossiers"]["fieldEvidenceReleaseClearanceLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldEvidenceReleaseClearanceLedger"]["summary"]["blockedCount"] >= 0
    assert state["industrialDossiers"]["fieldEvidenceReleaseClearanceLedger"]["clearanceRules"]
    assert state["industrialDossiers"]["spatialExecutionDrillLedger"]["mode"] == "industrial_spatial_execution_drill_ledger"
    assert len(state["industrialDossiers"]["spatialExecutionDrillLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["spatialExecutionDrillLedger"]["summary"]["frameCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["spatialExecutionDrillLedger"]["drillRules"]
    assert state["industrialDossiers"]["observedDrillVarianceLedger"]["mode"] == "industrial_observed_drill_variance_ledger"
    assert len(state["industrialDossiers"]["observedDrillVarianceLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["observedDrillVarianceLedger"]["summary"]["recalibrationCount"] >= 0
    assert state["industrialDossiers"]["observedDrillVarianceLedger"]["varianceRules"]
    assert state["industrialDossiers"]["industrialAcceptanceCertificationLedger"]["mode"] == "industrial_acceptance_certification_ledger"
    assert len(state["industrialDossiers"]["industrialAcceptanceCertificationLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialAcceptanceCertificationLedger"]["summary"]["demoCertifiedCount"] >= 0
    assert state["industrialDossiers"]["industrialAcceptanceCertificationLedger"]["certificationRules"]
    assert state["industrialDossiers"]["productionEvidenceAcquisitionLedger"]["mode"] == "industrial_production_evidence_acquisition_ledger"
    assert len(state["industrialDossiers"]["productionEvidenceAcquisitionLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["productionEvidenceAcquisitionLedger"]["summary"]["feedAcquisitionCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["productionEvidenceAcquisitionLedger"]["acquisitionRules"]
    assert state["industrialDossiers"]["productionDataIngestionContract"]["mode"] == "industrial_production_data_ingestion_contract"
    assert len(state["industrialDossiers"]["productionDataIngestionContract"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["productionDataIngestionContract"]["summary"]["feedContractCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["productionDataIngestionContract"]["contractRules"]
    assert state["industrialDossiers"]["industrialPromotionCertificationGate"]["mode"] == "industrial_promotion_certification_gate"
    assert len(state["industrialDossiers"]["industrialPromotionCertificationGate"]["certificationRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialPromotionCertificationGate"]["summary"]["demoOnlyCount"] >= 0
    assert state["industrialDossiers"]["industrialPromotionCertificationGate"]["certificationRules"]
    assert state["industrialDossiers"]["fieldTrialProtocolLedger"]["mode"] == "industrial_field_trial_protocol_ledger"
    assert len(state["industrialDossiers"]["fieldTrialProtocolLedger"]["protocolRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldTrialProtocolLedger"]["summary"]["readyProtocolCount"] >= 0
    assert state["industrialDossiers"]["fieldTrialProtocolLedger"]["protocolRules"]
    assert state["industrialDossiers"]["fieldTrialExecutionEvidenceLedger"]["mode"] == "industrial_field_trial_execution_evidence_ledger"
    assert len(state["industrialDossiers"]["fieldTrialExecutionEvidenceLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldTrialExecutionEvidenceLedger"]["summary"]["runEvidenceCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldTrialExecutionEvidenceLedger"]["evidenceRules"]
    assert state["industrialDossiers"]["fieldTrialCloseoutLedger"]["mode"] == "industrial_field_trial_closeout_ledger"
    assert len(state["industrialDossiers"]["fieldTrialCloseoutLedger"]["closeoutRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["fieldTrialCloseoutLedger"]["summary"]["holdCount"] >= 0
    assert state["industrialDossiers"]["fieldTrialCloseoutLedger"]["closeoutRules"]
    assert state["industrialDossiers"]["industrialOperatingTimelineLedger"]["mode"] == "industrial_operating_timeline_ledger"
    assert len(state["industrialDossiers"]["industrialOperatingTimelineLedger"]["timelineRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialOperatingTimelineLedger"]["summary"]["eventCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialOperatingTimelineLedger"]["summary"]["mapBoundEventCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialOperatingTimelineLedger"]["timelineRules"]
    assert state["industrialDossiers"]["incidentCommandDecisionLog"]["mode"] == "industrial_incident_command_decision_log"
    assert len(state["industrialDossiers"]["incidentCommandDecisionLog"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["incidentCommandDecisionLog"]["summary"]["approvalRequiredCount"] >= 1
    assert state["industrialDossiers"]["incidentCommandDecisionLog"]["commandRules"]
    assert state["industrialDossiers"]["industrialActionReplayLedger"]["mode"] == "industrial_action_replay_ledger"
    assert len(state["industrialDossiers"]["industrialActionReplayLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialActionReplayLedger"]["summary"]["frameCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialActionReplayLedger"]["replayRules"]
    assert state["industrialDossiers"]["physicalMovementProofLedger"]["mode"] == "industrial_physical_movement_proof_ledger"
    assert len(state["industrialDossiers"]["physicalMovementProofLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["physicalMovementProofLedger"]["summary"]["pathProofCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["physicalMovementProofLedger"]["proofRules"]
    assert state["industrialDossiers"]["telemetryAcceptanceLedger"]["mode"] == "industrial_telemetry_acceptance_ledger"
    assert len(state["industrialDossiers"]["telemetryAcceptanceLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["telemetryAcceptanceLedger"]["summary"]["acceptanceGateCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["telemetryAcceptanceLedger"]["acceptanceRules"]
    assert state["industrialDossiers"]["outcomeAccountabilityLedger"]["mode"] == "industrial_outcome_accountability_ledger"
    assert len(state["industrialDossiers"]["outcomeAccountabilityLedger"]["caseRows"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["outcomeAccountabilityLedger"]["summary"]["rollbackArmedCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["outcomeAccountabilityLedger"]["accountabilityRules"]
    assert state["industrialDossiers"]["industrialCaseFileSynthesis"]["mode"] == "industrial_case_file_synthesis"
    assert len(state["industrialDossiers"]["industrialCaseFileSynthesis"]["caseFiles"]) == state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialCaseFileSynthesis"]["summary"]["completeProofStackCount"] >= state["industrialDossiers"]["summary"]["caseCount"]
    assert state["industrialDossiers"]["industrialCaseFileSynthesis"]["synthesisRules"]
    assert state["industrialDossiers"]["industrialStandardsMatrix"]["mode"] == "industrial_standards_matrix"
    assert state["industrialDossiers"]["industrialStandardsMatrix"]["summary"]["status"] == "ready"
    assert state["industrialDossiers"]["industrialStandardsMatrix"]["summary"]["standardCount"] >= 7
    assert not state["industrialDossiers"]["industrialStandardsMatrix"]["summary"]["reviewCount"]
    assert {"ontology_asset_model", "spatial_physical_model", "policy_governance", "receiver_action_surface", "branch_counterfactuals", "human_approval_audit", "field_calibration"}.issubset(
        {row["id"] for row in state["industrialDossiers"]["industrialStandardsMatrix"]["standards"]}
    )
    assert state["industrialDossiers"]["industrialDeploymentReadiness"]["mode"] == "industrial_deployment_readiness"
    assert state["industrialDossiers"]["industrialDeploymentReadiness"]["deploymentState"] == "demo_ready_not_production_ready"
    assert state["industrialDossiers"]["industrialDeploymentReadiness"]["summary"]["demoReady"] is True
    assert state["industrialDossiers"]["industrialDeploymentReadiness"]["summary"]["productionReady"] is False
    assert state["industrialDossiers"]["industrialDeploymentReadiness"]["productionBlockers"]
    assert state["industrialDossiers"]["industrialOwnershipModel"]["mode"] == "industrial_ownership_raci_model"
    assert state["industrialDossiers"]["industrialOwnershipModel"]["summary"]["status"] == "ready"
    assert state["industrialDossiers"]["industrialOwnershipModel"]["summary"]["ownershipCoveragePct"] == 100
    assert state["industrialDossiers"]["industrialOwnershipModel"]["domainRaci"]
    assert state["industrialDossiers"]["industrialOwnershipModel"]["receiverRaci"]
    assert state["industrialDossiers"]["industrialOwnershipModel"]["productionBlockerOwners"]
    assert state["industrialDossiers"]["summary"]["qualityScore"] >= 90
    assert state["industrialDossiers"]["summary"]["blockingGapCount"] == 0
    assert state["industrialDossiers"]["quality"]["overallScore"] >= 90
    assert state["industrialDossiers"]["qualityGate"]["readyThreshold"] == 90
    first_dossier = state["industrialDossiers"]["dossiers"][0]
    assert first_dossier["operatingThesis"]["claim"]
    assert first_dossier["quality"]["status"] == "ready"
    assert first_dossier["evidenceProvenance"]
    assert {"actionConflictSimulation", "physicalDynamics", "externalSystems", "temporalConsequences"}.issubset(
        {row["sourceLayer"] for row in first_dossier["evidenceProvenance"]}
    )
    assert first_dossier["policyReasoning"]["approvalStandard"]
    assert first_dossier["governedApprovalPackage"]["mode"] == "governed_operator_approval_package"
    assert first_dossier["governedApprovalPackage"]["authorityBoundary"]["humanApprovalRequired"] is True
    assert first_dossier["governedApprovalPackage"]["authorityBoundary"]["autoExecuteAllowed"] is False
    assert first_dossier["governedApprovalPackage"]["receiverWrites"]
    assert first_dossier["governedApprovalPackage"]["rollbackAuthority"]["trigger"]
    assert first_dossier["dataQualityCalibration"]["mode"] == "industrial_data_quality_calibration"
    assert first_dossier["dataQualityCalibration"]["confidenceScore"] >= 70
    assert first_dossier["dataQualityCalibration"]["freshnessRows"]
    assert first_dossier["dataQualityCalibration"]["missingTelemetry"]
    assert first_dossier["dataQualityCalibration"]["calibrationRequirements"]
    assert first_dossier["telemetryContract"]["mode"] == "industrial_case_telemetry_contract"
    assert first_dossier["telemetryContract"]["sourceBindings"]
    assert first_dossier["telemetryContract"]["freshnessRules"]
    assert first_dossier["telemetryContract"]["ownership"]
    assert first_dossier["telemetryContract"]["decisionReadiness"]["requiredLayers"]
    assert first_dossier["telemetryContract"]["decisionReadiness"]["availableLayers"]
    assert first_dossier["telemetryContract"]["decisionReadiness"]["missingRequiredLayers"] == []
    assert first_dossier["telemetryContract"]["mutationGuards"]
    assert first_dossier["fieldSignalReconciliation"]["mode"] == "industrial_field_signal_reconciliation"
    assert first_dossier["fieldSignalReconciliation"]["agreementScore"] is not None
    assert first_dossier["fieldSignalReconciliation"]["sourceRows"]
    assert first_dossier["fieldSignalReconciliation"]["crossChecks"]
    assert first_dossier["fieldSignalReconciliation"]["freshnessEvidence"]
    assert first_dossier["fieldSignalReconciliation"]["watchMetricBindings"]
    assert first_dossier["fieldSignalReconciliation"]["approvalImpact"]
    assert first_dossier["fieldExecutionHandoff"]["mode"] == "industrial_field_execution_handoff"
    assert first_dossier["fieldExecutionHandoff"]["incidentCommand"]["commander"]
    assert first_dossier["fieldExecutionHandoff"]["stagingPlan"]["primaryArea"]
    assert first_dossier["fieldExecutionHandoff"]["dispatches"]
    assert first_dossier["fieldExecutionHandoff"]["guestCommunication"]["message"]
    assert len(first_dossier["fieldExecutionHandoff"]["acknowledgementGates"]) >= 3
    assert first_dossier["fieldExecutionHandoff"]["abortCriteria"]
    assert first_dossier["caseExecutionRunbook"]["mode"] == "industrial_case_execution_runbook"
    assert {step["id"] for step in first_dossier["caseExecutionRunbook"]["lifecycle"]} >= {"observe", "simulate", "policy_gate", "operator_approval", "receiver_write", "verify"}
    assert first_dossier["caseExecutionRunbook"]["owners"]
    assert first_dossier["caseExecutionRunbook"]["escalationRules"]
    assert first_dossier["caseExecutionRunbook"]["completionCriteria"]
    assert first_dossier["closedLoopVerification"]["mode"] == "closed_loop_verification_plan"
    assert first_dossier["closedLoopVerification"]["observationWindows"]
    assert first_dossier["closedLoopVerification"]["receiverReceipts"]
    assert first_dossier["closedLoopVerification"]["projectedVsObservedChecks"]
    assert first_dossier["closedLoopVerification"]["rollbackTriggers"]
    assert first_dossier["closedLoopVerification"]["learningCapture"]
    assert first_dossier["spatialCausalityTrace"]["mode"] == "map_object_causality_trace"
    assert first_dossier["spatialCausalityTrace"]["zones"]
    assert first_dossier["spatialCausalityTrace"]["paths"]
    assert first_dossier["spatialCausalityTrace"]["queues"]
    assert first_dossier["spatialCausalityTrace"]["branchSpatialEffects"]
    assert first_dossier["mapObjectEvidenceIndex"]["mode"] == "industrial_map_object_evidence_index"
    assert first_dossier["mapObjectEvidenceIndex"]["scale"]
    assert first_dossier["mapObjectEvidenceIndex"]["objectRows"]
    assert first_dossier["mapObjectEvidenceIndex"]["pathRows"]
    assert first_dossier["mapObjectEvidenceIndex"]["queueRows"]
    assert first_dossier["mapObjectEvidenceIndex"]["receiverLinks"]
    assert first_dossier["mapObjectEvidenceIndex"]["coverage"]["totalIndexedObjects"] > 0
    assert first_dossier["mapObjectEvidenceIndex"]["coverage"]["coordinateCoveragePct"] is not None
    assert first_dossier["parkRealityModel"]["mode"] == "case_specific_park_reality_model"
    assert first_dossier["parkRealityModel"]["operatingPhase"]["phase"]
    assert first_dossier["parkRealityModel"]["localTopology"]["zones"]
    assert first_dossier["parkRealityModel"]["localTopology"]["paths"]
    assert first_dossier["parkRealityModel"]["capacityEnvelope"]["zonePressure"]
    assert first_dossier["parkRealityModel"]["capacityEnvelope"]["pathBottlenecks"]
    assert first_dossier["parkRealityModel"]["serviceDependencies"]["receiverSystems"]
    assert first_dossier["parkRealityModel"]["serviceDependencies"]["guestSegments"]
    assert first_dossier["parkRealityModel"]["failurePropagation"]
    assert first_dossier["liveOperatingSceneModel"]["mode"] == "industrial_live_operating_scene_model"
    assert first_dossier["liveOperatingSceneModel"]["sceneClock"]
    assert first_dossier["liveOperatingSceneModel"]["sceneThesis"]
    assert first_dossier["liveOperatingSceneModel"]["actors"]
    assert first_dossier["liveOperatingSceneModel"]["physicalScene"]["zones"]
    assert first_dossier["liveOperatingSceneModel"]["physicalScene"]["paths"]
    assert first_dossier["liveOperatingSceneModel"]["physicalScene"]["queues"]
    assert first_dossier["liveOperatingSceneModel"]["bottlenecks"]
    assert first_dossier["liveOperatingSceneModel"]["serviceKinetics"]
    assert first_dossier["liveOperatingSceneModel"]["agentBeliefState"]["primaryBelief"]
    assert first_dossier["liveOperatingSceneModel"]["uncertaintyRegister"]
    assert first_dossier["liveOperatingSceneModel"]["actionTrainingImplication"]
    assert first_dossier["causalGraph"]["mode"] == "typed_operating_causal_graph"
    assert first_dossier["causalGraph"]["nodes"]
    assert first_dossier["causalGraph"]["edges"]
    assert first_dossier["causalGraph"]["nodeCount"] >= 7
    assert first_dossier["causalGraph"]["edgeCount"] >= 6
    assert {"trigger", "physical_constraint", "affected_zone", "receiver_system", "policy_boundary", "selected_action", "target_outcome"}.issubset(
        {node["type"] for node in first_dossier["causalGraph"]["nodes"]}
    )
    assert first_dossier["counterfactualReplay"]["mode"] == "counterfactual_branch_replay_matrix"
    assert first_dossier["counterfactualReplay"]["rows"]
    assert first_dossier["counterfactualReplay"]["rowCount"] >= 9
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["counterfactualReplay"]["rows"]}
    )
    assert first_dossier["branchPhysicalImpactMatrix"]["mode"] == "industrial_branch_physical_impact_matrix"
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["branchPhysicalImpactMatrix"]["branchRows"]}
    )
    assert first_dossier["branchPhysicalImpactMatrix"]["subsystemMovement"]
    assert all(row["mapObjects"] and row["physicalDeltas"] and row["impactNarrative"] for row in first_dossier["branchPhysicalImpactMatrix"]["branchRows"])
    assert first_dossier["actionConsequenceSimulation"]["mode"] == "industrial_action_consequence_simulation"
    assert first_dossier["actionConsequenceSimulation"]["consequenceFrames"]
    assert first_dossier["actionConsequenceSimulation"]["causalMechanisms"]
    assert first_dossier["actionConsequenceSimulation"]["requiredLiveTelemetry"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["actionConsequenceSimulation"]["branchOutcomeSummary"]}
    )
    assert all(
        row["secondOrderEffects"] and row["rollbackAssessment"]
        for row in first_dossier["actionConsequenceSimulation"]["consequenceFrames"][:3]
    )
    assert first_dossier["commercialImpactLedger"]["mode"] == "industrial_commercial_impact_ledger"
    assert first_dossier["commercialImpactLedger"]["rows"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["commercialImpactLedger"]["rows"]}
    )
    assert first_dossier["commercialImpactLedger"]["summary"]["operatorRead"]
    assert first_dossier["commercialImpactLedger"]["requiredCalibration"]
    assert first_dossier["accessibilityEquityImpact"]["mode"] == "industrial_accessibility_equity_impact"
    assert first_dossier["accessibilityEquityImpact"]["protectedCohorts"]
    assert first_dossier["accessibilityEquityImpact"]["routeAccessChecks"]
    assert first_dossier["accessibilityEquityImpact"]["fairnessChecks"]
    assert first_dossier["accessibilityEquityImpact"]["requiredControls"]
    assert first_dossier["accessibilityEquityImpact"]["equityScore"] is not None
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["accessibilityEquityImpact"]["branchEquityComparison"]}
    )
    assert first_dossier["resourceFeasibilityMatrix"]["mode"] == "industrial_resource_feasibility_matrix"
    assert first_dossier["resourceFeasibilityMatrix"]["laborEnvelope"]
    assert first_dossier["resourceFeasibilityMatrix"]["receiverExecutionRows"]
    assert first_dossier["resourceFeasibilityMatrix"]["timeCriticalPath"]
    assert first_dossier["resourceFeasibilityMatrix"]["resourceConflicts"]
    assert first_dossier["resourceFeasibilityMatrix"]["requiredOperatorChecks"]
    assert first_dossier["resourceFeasibilityMatrix"]["feasibilityScore"] is not None
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["resourceFeasibilityMatrix"]["branchFeasibilityComparison"]}
    )
    assert first_dossier["policyClauseTrace"]["mode"] == "industrial_policy_clause_trace"
    assert first_dossier["policyClauseTrace"]["appliedPolicyRefs"]
    assert first_dossier["policyClauseTrace"]["clauseRows"]
    assert first_dossier["policyClauseTrace"]["blockedActionTests"]
    assert first_dossier["policyClauseTrace"]["operatorApprovalQuestions"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["policyClauseTrace"]["branchPolicyVerdicts"]}
    )
    assert all(row["policyBookId"] and row["requiredEvidenceStatus"] for row in first_dossier["policyClauseTrace"]["clauseRows"])
    assert first_dossier["spatialPhysicsEnvelope"]["mode"] == "industrial_spatial_physics_envelope"
    assert first_dossier["spatialPhysicsEnvelope"]["physicsScore"] is not None
    assert first_dossier["spatialPhysicsEnvelope"]["routePhysics"]
    assert first_dossier["spatialPhysicsEnvelope"]["queueGeometry"]
    assert first_dossier["spatialPhysicsEnvelope"]["zoneLoad"]
    assert first_dossier["spatialPhysicsEnvelope"]["emergencyAndServiceAccess"]
    assert first_dossier["spatialPhysicsEnvelope"]["operatorChecks"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["spatialPhysicsEnvelope"]["branchPhysicsComparison"]}
    )
    assert first_dossier["physicalPropagationModel"]["mode"] == "industrial_physical_propagation_model"
    assert first_dossier["physicalPropagationModel"]["confidenceScore"] is not None
    assert len(first_dossier["physicalPropagationModel"]["chain"]) >= 5
    assert first_dossier["physicalPropagationModel"]["tripwires"]
    assert first_dossier["physicalPropagationModel"]["confidenceDrivers"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["physicalPropagationModel"]["branchPropagationEffects"]}
    )
    assert first_dossier["historicalPrecedentMatrix"]["mode"] == "industrial_historical_precedent_matrix"
    assert first_dossier["historicalPrecedentMatrix"]["precedentCoverage"]["datasetId"]
    assert first_dossier["historicalPrecedentMatrix"]["matchedPrecedents"]
    assert first_dossier["historicalPrecedentMatrix"]["recurringFailureModes"]
    assert first_dossier["historicalPrecedentMatrix"]["knownEffectiveControls"]
    assert first_dossier["historicalPrecedentMatrix"]["confidenceCalibration"]["mustCalibrateWith"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["historicalPrecedentMatrix"]["branchPrecedentVerdicts"]}
    )
    assert first_dossier["guestCommunicationPlan"]["mode"] == "industrial_guest_communication_plan"
    assert first_dossier["guestCommunicationPlan"]["communicationObjective"]
    assert first_dossier["guestCommunicationPlan"]["audiencePlans"]
    assert first_dossier["guestCommunicationPlan"]["channelPlan"]
    assert first_dossier["guestCommunicationPlan"]["promiseBoundaries"]
    assert first_dossier["guestCommunicationPlan"]["trustRiskControls"]
    assert first_dossier["guestCommunicationPlan"]["rollbackMessaging"]
    assert first_dossier["guestCommunicationPlan"]["approvalRequiredFor"]
    assert first_dossier["guestCommunicationPlan"]["measurementPlan"]
    assert first_dossier["behavioralResponseModel"]["mode"] == "industrial_behavioral_response_model"
    assert first_dossier["behavioralResponseModel"]["readinessScore"] is not None
    assert first_dossier["behavioralResponseModel"]["averageComplianceEstimatePct"] is not None
    assert first_dossier["behavioralResponseModel"]["segmentBehavior"]
    assert first_dossier["behavioralResponseModel"]["staffAndReceiverResponse"]
    assert first_dossier["behavioralResponseModel"]["trustFeedbackLoop"]["watchSignals"]
    assert first_dossier["behavioralResponseModel"]["criticalAssumptions"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["behavioralResponseModel"]["branchBehaviorComparison"]}
    )
    assert first_dossier["operationalConstraintRegister"]["mode"] == "industrial_operational_constraint_register"
    assert first_dossier["operationalConstraintRegister"]["hardConstraints"]
    assert first_dossier["operationalConstraintRegister"]["softTradeoffs"]
    assert first_dossier["operationalConstraintRegister"]["goNoGo"]["state"]
    assert first_dossier["operationalConstraintRegister"]["escalationPath"]
    assert {"no_action", "fast_local_action", "governed_agent_action"}.issubset(
        {row["branch"] for row in first_dossier["operationalConstraintRegister"]["branchConstraintVerdicts"]}
    )
    assert first_dossier["releaseDecisionRecord"]["mode"] == "industrial_release_decision_record"
    assert first_dossier["releaseDecisionRecord"]["releaseState"]
    assert first_dossier["releaseDecisionRecord"]["approvedVersion"]["version"]
    assert first_dossier["releaseDecisionRecord"]["approvalBoundary"]["humanApprovalRequired"] is True
    assert first_dossier["releaseDecisionRecord"]["signoffMatrix"]
    assert first_dossier["releaseDecisionRecord"]["releaseConditions"]
    assert first_dossier["releaseDecisionRecord"]["draftOnlyBoundaries"]
    assert first_dossier["releaseDecisionRecord"]["postReleaseObligations"]
    assert first_dossier["releaseDecisionRecord"]["freshnessAtRelease"]
    assert first_dossier["releaseAuthorityDecision"]["mode"] == "industrial_release_authority_decision"
    assert first_dossier["releaseAuthorityDecision"]["liveActionAuthority"]
    assert first_dossier["releaseAuthorityDecision"]["autoExecuteAllowed"] is False
    assert first_dossier["releaseAuthorityDecision"]["authorityChecks"]
    assert first_dossier["releaseAuthorityDecision"]["allowedNextStep"]
    assert first_dossier["executionReadinessProof"]["mode"] == "industrial_execution_readiness_proof"
    assert first_dossier["executionReadinessProof"]["readinessState"]
    assert first_dossier["executionReadinessProof"]["readyForLiveExecution"] is False
    assert first_dossier["executionReadinessProof"]["readinessScore"] is not None
    assert {"people_and_roles", "receiver_acknowledgement", "space_and_access", "guest_communications", "service_rate_and_timing", "rollback_and_observation", "telemetry_and_authority"}.issubset(
        {row["id"] for row in first_dossier["executionReadinessProof"]["executionChecks"]}
    )
    assert first_dossier["executionReadinessProof"]["requiredBeforeDispatch"]
    assert first_dossier["executionReadinessProof"]["caseSceneEvidence"]["bottlenecks"] >= 1
    assert first_dossier["releaseRemediationPlan"]["mode"] == "industrial_release_remediation_plan"
    assert first_dossier["releaseRemediationPlan"]["remediationState"]
    assert first_dossier["releaseRemediationPlan"]["tasks"]
    assert first_dossier["releaseRemediationPlan"]["recheckSequence"]
    assert first_dossier["releaseRemediationPlan"]["completionCriteria"]
    assert first_dossier["operatingProcedureDelta"]["mode"] == "industrial_operating_procedure_delta"
    assert first_dossier["operatingProcedureDelta"]["procedureDeltas"]
    assert first_dossier["operatingProcedureDelta"]["runbookStepUpdates"]
    assert first_dossier["operatingProcedureDelta"]["policyPatchCandidates"]
    assert first_dossier["operatingProcedureDelta"]["promotionGate"]["humanReviewRequired"] is True
    assert first_dossier["decisionReproducibilityManifest"]["mode"] == "industrial_decision_reproducibility_manifest"
    assert first_dossier["decisionReproducibilityManifest"]["manifestHash"]
    assert first_dossier["decisionReproducibilityManifest"]["simulatorVersion"]
    assert len(first_dossier["decisionReproducibilityManifest"]["inputArtifacts"]) >= 5
    assert first_dossier["decisionReproducibilityManifest"]["branchIds"]
    assert first_dossier["decisionReproducibilityManifest"]["expectedDeterministicOutputs"]["branchScores"]
    assert first_dossier["decisionReproducibilityManifest"]["replayInstructions"]
    assert first_dossier["decisionReproducibilityManifest"]["reproducibilityGate"]["productionReady"] is False
    assert first_dossier["chainOfCustodyAuditLog"]["mode"] == "industrial_chain_of_custody_audit_log"
    assert first_dossier["chainOfCustodyAuditLog"]["auditId"]
    assert first_dossier["chainOfCustodyAuditLog"]["custodyRows"]
    assert first_dossier["chainOfCustodyAuditLog"]["mutationAuthority"]
    assert first_dossier["chainOfCustodyAuditLog"]["immutableTraceCheckpoints"]
    assert first_dossier["chainOfCustodyAuditLog"]["evidenceHashInputs"]
    assert first_dossier["chainOfCustodyAuditLog"]["auditReplayInstructions"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["mode"] == "industrial_field_calibration_backtest_plan"
    assert first_dossier["fieldCalibrationBacktestPlan"]["requiredDatasets"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["backtestSuites"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["acceptanceThresholds"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["driftTriggers"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["learningCapturePlan"]
    assert first_dossier["fieldCalibrationBacktestPlan"]["syntheticLimitations"]
    assert len(first_dossier["actionTrainingFrame"]) == 3
    assert first_dossier["simulatedBranchComparison"]["mode"] == "dossier_three_branch_physical_simulation"
    assert {branch["id"] for branch in first_dossier["simulatedBranchComparison"]["branches"]} == {
        "no_action",
        "fast_local_action",
        "governed_agent_action",
    }
    fast_local_branch = next(branch for branch in first_dossier["simulatedBranchComparison"]["branches"] if branch["id"] == "fast_local_action")
    assert fast_local_branch["decision_basis"]["sideEffectProfile"] != "none"
    assert fast_local_branch["decision_basis"]["operatorHypothesis"]
    assert fast_local_branch["score_adjustment"] <= 0
    fast_profiles = {
        next(branch for branch in dossier["simulatedBranchComparison"]["branches"] if branch["id"] == "fast_local_action")["decision_basis"]["sideEffectProfile"]
        for dossier in state["industrialDossiers"]["dossiers"]
    }
    assert len(fast_profiles) >= 3
    lost_child_dossier = next(dossier for dossier in state["industrialDossiers"]["dossiers"] if "lost_child" in dossier["id"])
    lost_child_fast = next(branch for branch in lost_child_dossier["simulatedBranchComparison"]["branches"] if branch["id"] == "fast_local_action")
    assert lost_child_fast["decision_basis"]["actionId"] == "fast_security_surge"
    assert first_dossier["simulatedBranchComparison"]["selected_branch"] in {
        "no_action",
        "fast_local_action",
        "governed_agent_action",
    }
    assert first_dossier["operatingScorecard"]["mode"] == "industrial_operating_scorecard"
    assert {row["branch"] for row in first_dossier["operatingScorecard"]["scoreRows"]} == {
        "no_action",
        "fast_local_action",
        "governed_agent_action",
    }
    assert first_dossier["operatingScorecard"]["selectedBranch"] in {
        "no_action",
        "fast_local_action",
        "governed_agent_action",
    }
    assert first_dossier["operatingScorecard"]["tradeoffLedger"]
    assert first_dossier["operatingScorecard"]["dimensionWeights"]["safety"] > 0
    assert first_dossier["assumptionSensitivityAnalysis"]["mode"] == "industrial_assumption_sensitivity_analysis"
    assert first_dossier["assumptionSensitivityAnalysis"]["assumptions"]
    assert first_dossier["assumptionSensitivityAnalysis"]["stressTests"]
    assert first_dossier["assumptionSensitivityAnalysis"]["flipConditions"]
    assert first_dossier["assumptionSensitivityAnalysis"]["confidenceDrivers"]
    assert first_dossier["assumptionSensitivityAnalysis"]["selectedBranch"] in {
        "no_action",
        "fast_local_action",
        "governed_agent_action",
    }
    assert first_dossier["assumptionSensitivityAnalysis"]["operatingMargin"] is not None
    assert first_dossier["operationalStressRehearsal"]["mode"] == "industrial_operational_stress_rehearsal"
    assert first_dossier["operationalStressRehearsal"]["branchSurvivalScore"] is not None
    assert first_dossier["operationalStressRehearsal"]["releasePosture"]
    assert len(first_dossier["operationalStressRehearsal"]["rehearsalScenarios"]) >= 4
    assert first_dossier["operationalStressRehearsal"]["escalationTriggers"]
    assert first_dossier["independentReviewBoard"]["mode"] == "independent_operating_review_board"
    assert first_dossier["independentReviewBoard"]["reviews"]
    assert {"safety_reviewer", "operations_reviewer", "data_quality_reviewer", "commercial_guest_recovery_reviewer", "red_team_reviewer"}.issubset(
        {review["reviewer"] for review in first_dossier["independentReviewBoard"]["reviews"]}
    )
    assert first_dossier["independentReviewBoard"]["releaseDecision"]
    assert first_dossier["independentReviewBoard"]["residualRisks"]
    assert all(branch["simulatedOutcome"]["deltaFromNow"] for branch in first_dossier["actionTrainingFrame"])
    assert first_dossier["verificationPlan"]["watchConditions"]
    assert first_dossier["decisionTelemetrySnapshot"]["mode"] == "industrial_decision_telemetry_snapshot"
    assert first_dossier["decisionTelemetrySnapshot"]["queueRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["pathRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["foodRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["staffingRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["receiverRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["guestSegmentRows"]
    assert first_dossier["decisionTelemetrySnapshot"]["thresholdBreaches"]
    assert first_dossier["decisionTelemetrySnapshot"]["sourceLineage"]["mode"] == "telemetry_source_lineage"
    assert first_dossier["decisionTelemetrySnapshot"]["productionAcceptanceGates"]
    assert first_dossier["decisionTelemetrySnapshot"]["telemetryCertification"]["mode"] == "decision_telemetry_certification"
    assert first_dossier["decisionTelemetrySnapshot"]["telemetryCertification"]["structuralReady"] is True
    assert first_dossier["decisionTelemetrySnapshot"]["telemetryCertification"]["productionReady"] is False
    assert first_dossier["decisionTelemetrySnapshot"]["telemetryCertification"]["blockedGateCount"] >= 1
    assert {row["rowFamily"] for row in first_dossier["decisionTelemetrySnapshot"]["productionAcceptanceGates"]} >= {
        "queueRows",
        "pathRows",
        "foodRows",
        "staffingRows",
        "receiverRows",
        "guestSegmentRows",
    }
    assert first_dossier["decisionTelemetrySnapshot"]["queueRows"][0]["sourceIdentity"]["sourceSystemId"]
    assert first_dossier["decisionTelemetrySnapshot"]["queueRows"][0]["sourceIdentity"]["eventTime"]
    assert first_dossier["decisionTelemetrySnapshot"]["thresholdBreaches"][0]["sourceIdentity"]["owner"]
    assert first_dossier["decisionTelemetrySnapshot"]["freshness"]["productionRequirement"]
    assert "physicalDynamics" in first_dossier["auditStandard"]["traceKeys"]
    assert conflicts
    assert {conflict["domain"] for conflict in conflicts} >= {
        "guest_flow_food_capacity",
        "labor_certification_coverage",
        "energy_weather_guest_safety",
        "guest_care_security",
        "ride_safety_maintenance",
        "entertainment_event_flow",
        "commercial_fairness_guest_trust",
    }
    assert len({conflict["caseType"] for conflict in conflicts}) >= 7
    assert all(conflict["affectedObjects"] for conflict in conflicts)
    assert all(conflict["agentMustReason"] for conflict in conflicts)
    assert all(conflict["receiverImpacts"] for conflict in conflicts)
    assert state["digitalTwin"]["realismModel"]["version"] == "realistic_ops_v1"
    assert "industrialDossiers" in state["digitalTwin"]["realismModel"]["objects"]
    assert any(segment["id"] == "accessibility_parties" for segment in state["guestSegments"])
    assert any(system["id"] == "worker_device" for system in state["externalSystems"]["systems"])


def test_physical_dynamics_move_guests_and_spill_queues_during_tick():
    run(park_simulation.reset_demo())
    initial = run(park_simulation.get_state())
    assert all(zone.get("areaSqM") for zone in initial["guestFlow"]["zones"])
    assert all(path.get("widthM") and path.get("lengthM") and path.get("maxFlowPerMinute") for path in initial["guestFlow"]["paths"])
    assert all(queue.get("lengthM") and queue.get("guestSpacingM") for queue in initial["physicalMap"]["queues"])

    run(park_simulation.step())
    state = run(park_simulation.get_state())
    dynamics = state["physicalDynamics"]

    assert dynamics["mode"] == "physical_guest_staff_service_dynamics"
    assert dynamics["routeMoves"] or dynamics["queueSpillbacks"]
    assert dynamics["spatialModel"]["zoneAreasSqM"]
    assert isinstance(dynamics["foodService"], list)
    assert any(spillback.get("physicalQueueM") for spillback in dynamics["queueSpillbacks"])
    assert dynamics["spatialModel"]["pathWidthsM"]
    assert any(move.get("flowCapacity") for move in dynamics["routeMoves"]) or dynamics["queueSpillbacks"]
    assert "physical_dynamics" in state["digitalTwin"]["lastTransition"]


def test_realism_model_blocks_optimization_around_active_safety_incident():
    run(park_simulation.reset_demo())
    try:
        example = find_synthetic_example("SYN-MIXED-CONFLICT-001")
        run(park_simulation.inject_synthetic_incident(injection_plan_for_example(example)))
        state = run(park_simulation.get_state())

        conflicts = state["actionConflictSimulation"]["conflicts"]
        assert conflicts[0]["id"] == "optimization_vs_incident_containment"
        assert conflicts[0]["status"] == "blocked"
        assert state["externalSystems"]["humanApprovalRequired"] is True
        assert any(system["id"] == "security_radio" and system["state"] == "human_only" for system in state["externalSystems"]["systems"])
    finally:
        run(park_simulation.reset_demo())


def test_three_branch_comparison_shows_bad_metric_action_and_governed_branch():
    run(park_simulation.reset_demo())
    comparison = run(park_simulation.run_action_branch_comparison(horizon_minutes=20, execute=False))
    branch_ids = {branch["id"] for branch in comparison["branches"]}

    assert comparison["mode"] == "three_branch_realism_comparison"
    assert {"no_action", "bad_metric_action", "governed_agent_action"} == branch_ids
    assert comparison["selected_branch"] in branch_ids
    assert comparison["rejected_branch"] in branch_ids
    bad = next(branch for branch in comparison["branches"] if branch["id"] == "bad_metric_action")
    governed = next(branch for branch in comparison["branches"] if branch["id"] == "governed_agent_action")
    assert bad["realism"]["explanation"]
    assert governed["realism"]["open_conflicts"]
    assert comparison["summary"]["why_agents_matter"]


def test_compact_case_endpoints_split_live_state_from_heavy_audit_packet():
    run(park_simulation.reset_demo())
    live = run(get_park_live_summary())
    cases = run(get_park_cases())
    heavy = run(get_industrial_dossiers())

    assert live["mode"] == "compact_live_operating_summary"
    assert live["dataPlane"]["hotState"] == "Firestore or Memorystore"
    assert live["operatingSummary"]["topPriorityCaseId"]
    assert live["activeCase"]["productionEvidence"]["feedCount"] >= 1
    assert live["caseIndexEndpoint"] == "/api/park/cases"

    assert cases["mode"] == "compact_case_index"
    assert cases["rows"]
    assert cases["storagePlan"]["auditPacketObject"].startswith("Cloud Storage")
    assert cases["rows"][0]["links"]["brief"].startswith("/api/park/cases/")
    assert "dossiers" not in cases
    assert len(json.dumps(cases, default=str)) < len(json.dumps(heavy, default=str)) // 10

    brief = run(get_park_case_brief(cases["rows"][0]["id"]))
    assert brief["mode"] == "case_operating_brief"
    assert brief["caseHeader"]["id"] == cases["rows"][0]["id"]
    assert brief["gcpMaterialization"]["auditPacketObject"].startswith("gs://")
    assert brief["evidencePointers"]["fullAuditPacket"].endswith("/packet")
    assert "portfolioContext" not in brief


def test_industrial_dossier_api_exposes_case_lookup_and_audit_manifest():
    run(park_simulation.reset_demo())
    payload = run(get_industrial_dossiers())
    assert payload["status"] == "ready"
    assert payload["summary"]["qualityScore"] >= 90
    assert payload["summary"]["blockingGapCount"] == 0
    assert payload["quality"]["overallScore"] >= 90
    assert not payload["quality"]["blockingGaps"]
    assert payload["summary"]["caseCount"] >= 7
    assert payload["summary"]["domainCoverageCount"] >= 7
    assert payload["summary"]["coverageGapCount"] == 0
    assert not payload["portfolioCoverage"]["coverageGaps"]
    assert payload["portfolioOperatingModel"]["mode"] == "industrial_portfolio_operating_model"
    assert payload["portfolioOperatingModel"]["assetInventory"]["receiverSystems"] >= 5
    assert payload["portfolioOperatingModel"]["spatialNetwork"]["bottlenecks"]
    assert payload["portfolioOperatingModel"]["governanceSurface"]["policyRefs"]
    assert payload["portfolioOperatingModel"]["coverageReadiness"]["coverageGaps"] == []
    assert payload["portfolioRiskRanking"]["mode"] == "industrial_portfolio_risk_ranking"
    assert payload["portfolioRiskRanking"]["rankingRows"]
    assert payload["portfolioRiskRanking"]["portfolioConflicts"]
    assert payload["caseIndex"][0]["portfolioPriority"]["rank"] >= 1
    assert payload["productionEvidenceGapRegister"]["mode"] == "industrial_production_evidence_gap_register"
    assert payload["productionEvidenceGapRegister"]["productionReady"] is False
    assert payload["productionEvidenceGapRegister"]["caseRows"]
    assert payload["productionEvidenceGapRegister"]["feedReadinessRows"]
    assert payload["caseIndex"][0]["productionEvidenceStatus"]["blockingGaps"]
    assert payload["fieldReplayValidationHarness"]["mode"] == "industrial_field_replay_validation_harness"
    assert payload["fieldReplayValidationHarness"]["caseRows"]
    assert payload["fieldReplayValidationHarness"]["summary"]["branchValidationRunCount"] >= payload["summary"]["caseCount"] * 3
    assert payload["caseIndex"][0]["fieldReplayValidation"]["validationRuns"]
    assert payload["capacityCertificationLedger"]["mode"] == "industrial_capacity_certification_ledger"
    assert payload["capacityCertificationLedger"]["caseRows"]
    assert payload["capacityCertificationLedger"]["summary"]["caseCount"] == payload["summary"]["caseCount"]
    assert payload["caseIndex"][0]["capacityCertification"]["capacityFindings"]
    assert payload["slaEscalationClock"]["mode"] == "industrial_sla_escalation_clock"
    assert payload["slaEscalationClock"]["caseRows"]
    assert payload["slaEscalationClock"]["summary"]["caseCount"] == payload["summary"]["caseCount"]
    assert payload["caseIndex"][0]["slaEscalation"]["clockRows"]
    assert payload["receiverExecutionContractLedger"]["mode"] == "industrial_receiver_execution_contract_ledger"
    assert payload["receiverExecutionContractLedger"]["caseRows"]
    assert payload["receiverExecutionContractLedger"]["summary"]["contractCount"] >= payload["summary"]["caseCount"]
    assert payload["caseIndex"][0]["receiverExecutionContract"]["contractRows"]
    assert payload["externalSystemExecutionEvidence"]["mode"] == "industrial_external_system_execution_evidence"
    assert payload["externalSystemExecutionEvidence"]["caseRows"]
    assert payload["caseIndex"][0]["externalExecutionEvidence"]["evidenceRows"]
    assert payload["caseIndex"][0]["externalExecutionEvidence"]["evidenceRows"][0]["preparedPayload"]["idempotencyKey"]
    assert payload["industrialDossierCompletenessAudit"]["mode"] == "industrial_dossier_completeness_audit"
    assert payload["industrialDossierCompletenessAudit"]["auditRows"]
    assert payload["caseIndex"][0]["dossierCompletenessAudit"]["proofFamilies"]
    assert payload["caseIndex"][0]["dossierCompletenessAudit"]["promotionBoundary"]
    assert payload["liveEvidenceDriftMonitor"]["mode"] == "industrial_live_evidence_drift_monitor"
    assert payload["liveEvidenceDriftMonitor"]["driftRows"]
    assert payload["caseIndex"][0]["liveEvidenceDrift"]["liveSignals"]
    assert payload["caseIndex"][0]["liveEvidenceDrift"]["requiredRecheck"]
    assert payload["observedOutcomeCalibrationLedger"]["mode"] == "industrial_observed_outcome_calibration_ledger"
    assert payload["observedOutcomeCalibrationLedger"]["calibrationRows"]
    assert payload["caseIndex"][0]["observedOutcomeCalibration"]["variance"]
    assert payload["caseIndex"][0]["observedOutcomeCalibration"]["trustDecision"]
    assert payload["varianceRootCauseLedger"]["mode"] == "industrial_variance_root_cause_ledger"
    assert payload["varianceRootCauseLedger"]["rootCauseRows"]
    assert payload["caseIndex"][0]["varianceRootCause"]["rootCauseRows"]
    assert payload["caseIndex"][0]["varianceRootCause"]["reuseDecision"]
    assert payload["industrialReviewDispositionLedger"]["mode"] == "industrial_review_disposition_ledger"
    assert payload["industrialReviewDispositionLedger"]["dispositionRows"]
    assert payload["caseIndex"][0]["reviewDisposition"]["signoffMatrix"]
    assert payload["caseIndex"][0]["reviewDisposition"]["reviewDisposition"]
    assert payload["industrialAuditExportManifest"]["mode"] == "industrial_audit_export_manifest"
    assert payload["industrialAuditExportManifest"]["packageRows"]
    assert payload["caseIndex"][0]["auditExportPackage"]["packageHash"]
    assert payload["caseIndex"][0]["auditExportPackage"]["artifactRows"]
    assert payload["dataLineageCertificationLedger"]["mode"] == "industrial_data_lineage_certification_ledger"
    assert payload["dataLineageCertificationLedger"]["certificationRows"]
    assert payload["caseIndex"][0]["dataLineageCertification"]["sourceSystemRows"]
    assert payload["caseIndex"][0]["dataLineageCertification"]["certificationDecision"]
    assert payload["policyRiskControlLedger"]["mode"] == "industrial_policy_risk_control_ledger"
    assert payload["policyRiskControlLedger"]["controlRows"]
    assert payload["caseIndex"][0]["policyRiskControl"]["controlRows"]
    assert payload["caseIndex"][0]["policyRiskControl"]["sensitiveFlags"]
    assert payload["caseWorkOrderExecutionLedger"]["mode"] == "industrial_case_work_order_execution_ledger"
    assert payload["caseWorkOrderExecutionLedger"]["caseRows"]
    assert payload["caseIndex"][0]["caseWorkOrderExecution"]["workOrders"]
    assert payload["caseIndex"][0]["caseWorkOrderExecution"]["acknowledgementPlan"]
    assert payload["fieldReceiptReconciliationLedger"]["mode"] == "industrial_field_receipt_reconciliation_ledger"
    assert payload["fieldReceiptReconciliationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldReceiptReconciliation"]["receiptRows"]
    assert payload["caseIndex"][0]["fieldReceiptReconciliation"]["productionBoundary"]
    assert payload["releaseBoardExceptionLedger"]["mode"] == "industrial_release_board_exception_ledger"
    assert payload["releaseBoardExceptionLedger"]["exceptionRows"]
    assert payload["caseIndex"][0]["releaseBoardException"]["exceptionDecision"]
    assert payload["caseIndex"][0]["releaseBoardException"]["signoffRows"]
    assert payload["scenarioCoverageCertificationLedger"]["mode"] == "industrial_scenario_coverage_certification_ledger"
    assert payload["scenarioCoverageCertificationLedger"]["certificationRows"]
    assert payload["caseIndex"][0]["scenarioCoverageCertification"]["drillFamilyRows"]
    assert payload["caseIndex"][0]["scenarioCoverageCertification"]["productionBoundary"]
    assert payload["operatorCompetencyEvaluationLedger"]["mode"] == "industrial_operator_competency_evaluation_ledger"
    assert payload["operatorCompetencyEvaluationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["operatorCompetencyEvaluation"]["evaluationTasks"]
    assert payload["caseIndex"][0]["operatorCompetencyEvaluation"]["scoringRubric"]
    assert payload["causalEpisodeTrainingLedger"]["mode"] == "industrial_causal_episode_training_ledger"
    assert payload["causalEpisodeTrainingLedger"]["caseRows"]
    assert payload["caseIndex"][0]["causalEpisodeTraining"]["episodeFrames"]
    assert payload["caseIndex"][0]["causalEpisodeTraining"]["physicalProofSummary"]
    assert payload["simulationValidityCalibrationLedger"]["mode"] == "industrial_simulation_validity_calibration_ledger"
    assert payload["simulationValidityCalibrationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["simulationValidityCalibration"]["assumptionRows"]
    assert payload["caseIndex"][0]["simulationValidityCalibration"]["falsificationChecks"]
    assert payload["fieldObservationProtocolLedger"]["mode"] == "industrial_field_observation_protocol_ledger"
    assert payload["fieldObservationProtocolLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldObservationProtocol"]["stationRows"]
    assert payload["caseIndex"][0]["fieldObservationProtocol"]["measurementProtocol"]
    assert payload["fieldEvidenceCaptureLedger"]["mode"] == "industrial_field_evidence_capture_ledger"
    assert payload["fieldEvidenceCaptureLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceCapture"]["formRows"]
    assert payload["caseIndex"][0]["fieldEvidenceCapture"]["custody"]
    assert payload["fieldEvidenceSampleLedger"]["mode"] == "industrial_field_evidence_sample_ledger"
    assert payload["fieldEvidenceSampleLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceSample"]["recordRows"]
    assert payload["caseIndex"][0]["fieldEvidenceSample"]["custodySummary"]
    assert payload["fieldEvidenceAdjudicationLedger"]["mode"] == "industrial_field_evidence_adjudication_ledger"
    assert payload["fieldEvidenceAdjudicationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceAdjudication"]["metricAdjudications"]
    assert payload["caseIndex"][0]["fieldEvidenceAdjudication"]["releaseImpact"]
    assert payload["fieldEvidenceRemediationLedger"]["mode"] == "industrial_field_evidence_remediation_ledger"
    assert payload["fieldEvidenceRemediationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceRemediation"]["remediationRows"]
    assert payload["caseIndex"][0]["fieldEvidenceRemediation"]["releaseHold"]
    assert payload["fieldEvidenceRemediationExecutionLedger"]["mode"] == "industrial_field_evidence_remediation_execution_ledger"
    assert payload["fieldEvidenceRemediationExecutionLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceRemediationExecution"]["executionRows"]
    assert payload["caseIndex"][0]["fieldEvidenceRemediationExecution"]["holdClearance"]
    assert payload["fieldEvidenceReleaseClearanceLedger"]["mode"] == "industrial_field_evidence_release_clearance_ledger"
    assert payload["fieldEvidenceReleaseClearanceLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldEvidenceReleaseClearance"]["signoffMatrix"]
    assert payload["caseIndex"][0]["fieldEvidenceReleaseClearance"]["clearancePacket"]
    assert payload["spatialExecutionDrillLedger"]["mode"] == "industrial_spatial_execution_drill_ledger"
    assert payload["spatialExecutionDrillLedger"]["caseRows"]
    assert payload["caseIndex"][0]["spatialExecutionDrill"]["drillFrames"]
    assert payload["caseIndex"][0]["spatialExecutionDrill"]["drillPacket"]
    assert payload["observedDrillVarianceLedger"]["mode"] == "industrial_observed_drill_variance_ledger"
    assert payload["observedDrillVarianceLedger"]["caseRows"]
    assert payload["caseIndex"][0]["observedDrillVariance"]["varianceRows"]
    assert payload["caseIndex"][0]["observedDrillVariance"]["variancePacket"]
    assert payload["industrialAcceptanceCertificationLedger"]["mode"] == "industrial_acceptance_certification_ledger"
    assert payload["industrialAcceptanceCertificationLedger"]["caseRows"]
    assert payload["caseIndex"][0]["industrialAcceptanceCertification"]["proofFamilyRows"]
    assert payload["caseIndex"][0]["industrialAcceptanceCertification"]["certificationPacket"]
    assert payload["productionEvidenceAcquisitionLedger"]["mode"] == "industrial_production_evidence_acquisition_ledger"
    assert payload["productionEvidenceAcquisitionLedger"]["caseRows"]
    assert payload["caseIndex"][0]["productionEvidenceAcquisition"]["feedAcquisitions"]
    assert payload["caseIndex"][0]["productionEvidenceAcquisition"]["acquisitionPacket"]
    assert payload["productionDataIngestionContract"]["mode"] == "industrial_production_data_ingestion_contract"
    assert payload["productionDataIngestionContract"]["caseRows"]
    assert payload["caseIndex"][0]["productionDataContract"]["feedContracts"]
    assert payload["caseIndex"][0]["productionDataContract"]["graduationCriteria"]
    assert payload["industrialPromotionCertificationGate"]["mode"] == "industrial_promotion_certification_gate"
    assert payload["industrialPromotionCertificationGate"]["certificationRows"]
    assert payload["caseIndex"][0]["promotionCertification"]["certificationChecks"]
    assert payload["caseIndex"][0]["promotionCertification"]["releaseBoundary"]
    assert payload["fieldTrialProtocolLedger"]["mode"] == "industrial_field_trial_protocol_ledger"
    assert payload["fieldTrialProtocolLedger"]["protocolRows"]
    assert payload["caseIndex"][0]["fieldTrialProtocol"]["trialScope"]
    assert payload["caseIndex"][0]["fieldTrialProtocol"]["stopRules"]
    assert payload["fieldTrialExecutionEvidenceLedger"]["mode"] == "industrial_field_trial_execution_evidence_ledger"
    assert payload["fieldTrialExecutionEvidenceLedger"]["caseRows"]
    assert payload["caseIndex"][0]["fieldTrialExecutionEvidence"]["observationCaptures"]
    assert payload["caseIndex"][0]["fieldTrialExecutionEvidence"]["trialOutcomeDisposition"]
    assert payload["fieldTrialCloseoutLedger"]["mode"] == "industrial_field_trial_closeout_ledger"
    assert payload["fieldTrialCloseoutLedger"]["closeoutRows"]
    assert payload["caseIndex"][0]["fieldTrialCloseout"]["trialResultRecord"]
    assert payload["caseIndex"][0]["fieldTrialCloseout"]["promotionDecision"]
    assert payload["industrialOperatingTimelineLedger"]["mode"] == "industrial_operating_timeline_ledger"
    assert payload["industrialOperatingTimelineLedger"]["timelineRows"]
    assert payload["caseIndex"][0]["operatingTimeline"]["eventRows"]
    assert payload["caseIndex"][0]["operatingTimeline"]["mapBindingSummary"]
    assert payload["incidentCommandDecisionLog"]["mode"] == "industrial_incident_command_decision_log"
    assert payload["incidentCommandDecisionLog"]["caseRows"]
    assert payload["caseIndex"][0]["incidentCommandDecision"]["decisionRecord"]
    assert payload["caseIndex"][0]["incidentCommandDecision"]["auditEvent"]["auditId"]
    assert payload["industrialActionReplayLedger"]["mode"] == "industrial_action_replay_ledger"
    assert payload["industrialActionReplayLedger"]["caseRows"]
    assert payload["caseIndex"][0]["actionReplay"]["timelineFrames"]
    assert payload["caseIndex"][0]["actionReplay"]["closedLoopWatch"]
    assert payload["physicalMovementProofLedger"]["mode"] == "industrial_physical_movement_proof_ledger"
    assert payload["physicalMovementProofLedger"]["caseRows"]
    assert payload["caseIndex"][0]["physicalMovementProof"]["mapObjectBinding"]
    assert payload["caseIndex"][0]["physicalMovementProof"]["pathProofRows"]
    assert payload["caseIndex"][0]["physicalMovementProof"]["queueProofRows"]
    assert payload["telemetryAcceptanceLedger"]["mode"] == "industrial_telemetry_acceptance_ledger"
    assert payload["telemetryAcceptanceLedger"]["caseRows"]
    assert payload["caseIndex"][0]["telemetryAcceptance"]["acceptanceGateRows"]
    assert payload["caseIndex"][0]["telemetryAcceptance"]["sourceContract"]
    assert payload["caseIndex"][0]["telemetryAcceptance"]["closedLoopAcceptance"]
    assert payload["outcomeAccountabilityLedger"]["mode"] == "industrial_outcome_accountability_ledger"
    assert payload["outcomeAccountabilityLedger"]["caseRows"]
    assert payload["caseIndex"][0]["outcomeAccountability"]["expectedOutcome"]
    assert payload["caseIndex"][0]["outcomeAccountability"]["observedEvidenceStatus"]
    assert payload["caseIndex"][0]["outcomeAccountability"]["rollbackPosture"]
    assert payload["industrialCaseFileSynthesis"]["mode"] == "industrial_case_file_synthesis"
    assert payload["industrialCaseFileSynthesis"]["caseFiles"]
    assert payload["caseIndex"][0]["caseFile"]["caseNarrative"]
    assert payload["caseIndex"][0]["caseFile"]["proofStack"]
    assert payload["caseIndex"][0]["caseFile"]["accountability"]
    assert payload["industrialStandardsMatrix"]["mode"] == "industrial_standards_matrix"
    assert payload["industrialStandardsMatrix"]["summary"]["status"] == "ready"
    assert payload["industrialStandardsMatrix"]["standards"]
    assert payload["industrialDeploymentReadiness"]["mode"] == "industrial_deployment_readiness"
    assert payload["industrialDeploymentReadiness"]["deploymentState"] == "demo_ready_not_production_ready"
    assert payload["industrialDeploymentReadiness"]["summary"]["productionReady"] is False
    assert payload["industrialDeploymentReadiness"]["productionBlockers"]
    assert payload["industrialOwnershipModel"]["mode"] == "industrial_ownership_raci_model"
    assert payload["industrialOwnershipModel"]["summary"]["ownershipCoveragePct"] == 100
    assert payload["industrialOwnershipModel"]["approvalEscalation"]
    assert len(payload["coverageMatrix"]) >= 7
    assert set(payload["auditManifest"]["requiredSections"]) >= {
        "operatingThesis",
        "physicalMechanism",
        "spatialCausalityTrace",
        "mapObjectEvidenceIndex",
        "parkRealityModel",
        "liveOperatingSceneModel",
        "causalGraph",
        "counterfactualReplay",
        "actionConsequenceSimulation",
        "commercialImpactLedger",
        "accessibilityEquityImpact",
        "resourceFeasibilityMatrix",
        "policyClauseTrace",
        "spatialPhysicsEnvelope",
        "physicalPropagationModel",
        "historicalPrecedentMatrix",
        "guestCommunicationPlan",
        "behavioralResponseModel",
        "operationalConstraintRegister",
        "releaseDecisionRecord",
        "releaseAuthorityDecision",
        "executionReadinessProof",
        "releaseRemediationPlan",
        "operatingProcedureDelta",
        "decisionReproducibilityManifest",
        "chainOfCustodyAuditLog",
        "fieldCalibrationBacktestPlan",
        "evidenceProvenance",
        "affectedOntology",
        "policyReasoning",
        "governedApprovalPackage",
        "dataQualityCalibration",
        "telemetryContract",
        "fieldSignalReconciliation",
        "decisionTelemetrySnapshot",
        "fieldExecutionHandoff",
        "caseExecutionRunbook",
        "closedLoopVerification",
        "receiverReadiness",
        "evidenceTimeline",
        "competingHypotheses",
        "actionTrainingFrame",
        "simulatedBranchComparison",
        "branchPhysicalImpactMatrix",
        "operatingScorecard",
        "assumptionSensitivityAnalysis",
        "operationalStressRehearsal",
        "independentReviewBoard",
        "verificationPlan",
        "auditStandard",
    }
    assert payload["auditManifest"]["qualityGate"]["readyThreshold"] == 90
    assert any("portfolio coverage" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("evidence provenance" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("simulated branch comparison" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("operating scorecard" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("operational stress rehearsal" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("spatial causality trace" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("map object evidence index" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("park reality model" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("live operating scene model" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("causal graph" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("counterfactual replay" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("branch physical impact matrix" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("action consequence simulation" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("commercial impact ledger" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("accessibility and equity impact" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("resource feasibility matrix" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("policy clause trace" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("spatial physics envelope" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("physical propagation model" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("historical precedent matrix" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("guest communication plan" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("behavioral response model" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("operational constraint register" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("release decision record" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("release authority decision" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("execution readiness proof" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("release remediation plan" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("operating procedure delta" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("decision reproducibility manifest" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("chain-of-custody audit log" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("field calibration" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("governed approval package" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("data quality calibration" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("telemetry contract" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("field signal reconciliation" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("decision-time telemetry snapshot" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("field execution handoff" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("case execution runbook" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("closed-loop verification" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("assumption sensitivity" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert any("independent review board" in check for check in payload["auditManifest"]["qualityGate"]["checks"])
    assert payload["caseIndex"][0]["quality"]["status"] == "ready"
    assert payload["caseIndex"][0]["trainingBranches"] == ["no_action", "fast_local_action", "governed_agent_action"]
    case_id = payload["caseIndex"][0]["sourceConflictId"]
    case_payload = run(get_industrial_dossier(case_id))
    dossier = case_payload["dossier"]
    assert dossier["sourceConflictId"] == case_id
    assert dossier["verificationPlan"]["rollbackTrigger"]
    assert case_payload["auditManifest"]["caseLookup"] == "/api/park/industrial-dossiers/{case_id}"
    broken_dossier = deepcopy(dossier)
    broken_dossier.pop("simulatedBranchComparison")
    broken_quality = score_industrial_dossier_quality(broken_dossier, payload["auditManifest"]["requiredSections"])
    assert broken_quality["status"] == "needs_review"
    assert "simulatedBranchComparison" in broken_quality["missing"]
    broken_scorecard = deepcopy(dossier)
    broken_scorecard.pop("operatingScorecard")
    broken_scorecard_quality = score_industrial_dossier_quality(broken_scorecard, payload["auditManifest"]["requiredSections"])
    assert broken_scorecard_quality["status"] == "needs_review"
    assert "operatingScorecard" in broken_scorecard_quality["missing"]
    broken_spatial = deepcopy(dossier)
    broken_spatial.pop("spatialCausalityTrace")
    broken_spatial_quality = score_industrial_dossier_quality(broken_spatial, payload["auditManifest"]["requiredSections"])
    assert broken_spatial_quality["status"] == "needs_review"
    assert "spatialCausalityTrace" in broken_spatial_quality["missing"]
    broken_map_index = deepcopy(dossier)
    broken_map_index.pop("mapObjectEvidenceIndex")
    broken_map_index_quality = score_industrial_dossier_quality(broken_map_index, payload["auditManifest"]["requiredSections"])
    assert broken_map_index_quality["status"] == "needs_review"
    assert "mapObjectEvidenceIndex" in broken_map_index_quality["missing"]
    broken_reality = deepcopy(dossier)
    broken_reality.pop("parkRealityModel")
    broken_reality_quality = score_industrial_dossier_quality(broken_reality, payload["auditManifest"]["requiredSections"])
    assert broken_reality_quality["status"] == "needs_review"
    assert "parkRealityModel" in broken_reality_quality["missing"]
    broken_scene = deepcopy(dossier)
    broken_scene.pop("liveOperatingSceneModel")
    broken_scene_quality = score_industrial_dossier_quality(broken_scene, payload["auditManifest"]["requiredSections"])
    assert broken_scene_quality["status"] == "needs_review"
    assert "liveOperatingSceneModel" in broken_scene_quality["missing"]
    broken_causal = deepcopy(dossier)
    broken_causal.pop("causalGraph")
    broken_causal_quality = score_industrial_dossier_quality(broken_causal, payload["auditManifest"]["requiredSections"])
    assert broken_causal_quality["status"] == "needs_review"
    assert "causalGraph" in broken_causal_quality["missing"]
    broken_replay = deepcopy(dossier)
    broken_replay.pop("counterfactualReplay")
    broken_replay_quality = score_industrial_dossier_quality(broken_replay, payload["auditManifest"]["requiredSections"])
    assert broken_replay_quality["status"] == "needs_review"
    assert "counterfactualReplay" in broken_replay_quality["missing"]
    broken_branch_impact = deepcopy(dossier)
    broken_branch_impact.pop("branchPhysicalImpactMatrix")
    broken_branch_impact_quality = score_industrial_dossier_quality(broken_branch_impact, payload["auditManifest"]["requiredSections"])
    assert broken_branch_impact_quality["status"] == "needs_review"
    assert "branchPhysicalImpactMatrix" in broken_branch_impact_quality["missing"]
    broken_consequence = deepcopy(dossier)
    broken_consequence.pop("actionConsequenceSimulation")
    broken_consequence_quality = score_industrial_dossier_quality(broken_consequence, payload["auditManifest"]["requiredSections"])
    assert broken_consequence_quality["status"] == "needs_review"
    assert "actionConsequenceSimulation" in broken_consequence_quality["missing"]
    broken_commercial = deepcopy(dossier)
    broken_commercial.pop("commercialImpactLedger")
    broken_commercial_quality = score_industrial_dossier_quality(broken_commercial, payload["auditManifest"]["requiredSections"])
    assert broken_commercial_quality["status"] == "needs_review"
    assert "commercialImpactLedger" in broken_commercial_quality["missing"]
    broken_accessibility = deepcopy(dossier)
    broken_accessibility.pop("accessibilityEquityImpact")
    broken_accessibility_quality = score_industrial_dossier_quality(broken_accessibility, payload["auditManifest"]["requiredSections"])
    assert broken_accessibility_quality["status"] == "needs_review"
    assert "accessibilityEquityImpact" in broken_accessibility_quality["missing"]
    broken_resource = deepcopy(dossier)
    broken_resource.pop("resourceFeasibilityMatrix")
    broken_resource_quality = score_industrial_dossier_quality(broken_resource, payload["auditManifest"]["requiredSections"])
    assert broken_resource_quality["status"] == "needs_review"
    assert "resourceFeasibilityMatrix" in broken_resource_quality["missing"]
    broken_policy_trace = deepcopy(dossier)
    broken_policy_trace.pop("policyClauseTrace")
    broken_policy_trace_quality = score_industrial_dossier_quality(broken_policy_trace, payload["auditManifest"]["requiredSections"])
    assert broken_policy_trace_quality["status"] == "needs_review"
    assert "policyClauseTrace" in broken_policy_trace_quality["missing"]
    broken_physics = deepcopy(dossier)
    broken_physics.pop("spatialPhysicsEnvelope")
    broken_physics_quality = score_industrial_dossier_quality(broken_physics, payload["auditManifest"]["requiredSections"])
    assert broken_physics_quality["status"] == "needs_review"
    assert "spatialPhysicsEnvelope" in broken_physics_quality["missing"]
    broken_precedent = deepcopy(dossier)
    broken_precedent.pop("historicalPrecedentMatrix")
    broken_precedent_quality = score_industrial_dossier_quality(broken_precedent, payload["auditManifest"]["requiredSections"])
    assert broken_precedent_quality["status"] == "needs_review"
    assert "historicalPrecedentMatrix" in broken_precedent_quality["missing"]
    broken_guest_comms = deepcopy(dossier)
    broken_guest_comms.pop("guestCommunicationPlan")
    broken_guest_comms_quality = score_industrial_dossier_quality(broken_guest_comms, payload["auditManifest"]["requiredSections"])
    assert broken_guest_comms_quality["status"] == "needs_review"
    assert "guestCommunicationPlan" in broken_guest_comms_quality["missing"]
    broken_constraints = deepcopy(dossier)
    broken_constraints.pop("operationalConstraintRegister")
    broken_constraints_quality = score_industrial_dossier_quality(broken_constraints, payload["auditManifest"]["requiredSections"])
    assert broken_constraints_quality["status"] == "needs_review"
    assert "operationalConstraintRegister" in broken_constraints_quality["missing"]
    broken_release = deepcopy(dossier)
    broken_release.pop("releaseDecisionRecord")
    broken_release_quality = score_industrial_dossier_quality(broken_release, payload["auditManifest"]["requiredSections"])
    assert broken_release_quality["status"] == "needs_review"
    assert "releaseDecisionRecord" in broken_release_quality["missing"]
    broken_authority = deepcopy(dossier)
    broken_authority.pop("releaseAuthorityDecision")
    broken_authority_quality = score_industrial_dossier_quality(broken_authority, payload["auditManifest"]["requiredSections"])
    assert broken_authority_quality["status"] == "needs_review"
    assert "releaseAuthorityDecision" in broken_authority_quality["missing"]
    broken_execution = deepcopy(dossier)
    broken_execution.pop("executionReadinessProof")
    broken_execution_quality = score_industrial_dossier_quality(broken_execution, payload["auditManifest"]["requiredSections"])
    assert broken_execution_quality["status"] == "needs_review"
    assert "executionReadinessProof" in broken_execution_quality["missing"]
    broken_remediation = deepcopy(dossier)
    broken_remediation.pop("releaseRemediationPlan")
    broken_remediation_quality = score_industrial_dossier_quality(broken_remediation, payload["auditManifest"]["requiredSections"])
    assert broken_remediation_quality["status"] == "needs_review"
    assert "releaseRemediationPlan" in broken_remediation_quality["missing"]
    broken_procedure_delta = deepcopy(dossier)
    broken_procedure_delta.pop("operatingProcedureDelta")
    broken_procedure_delta_quality = score_industrial_dossier_quality(broken_procedure_delta, payload["auditManifest"]["requiredSections"])
    assert broken_procedure_delta_quality["status"] == "needs_review"
    assert "operatingProcedureDelta" in broken_procedure_delta_quality["missing"]
    broken_reproducibility = deepcopy(dossier)
    broken_reproducibility.pop("decisionReproducibilityManifest")
    broken_reproducibility_quality = score_industrial_dossier_quality(broken_reproducibility, payload["auditManifest"]["requiredSections"])
    assert broken_reproducibility_quality["status"] == "needs_review"
    assert "decisionReproducibilityManifest" in broken_reproducibility_quality["missing"]
    broken_custody = deepcopy(dossier)
    broken_custody.pop("chainOfCustodyAuditLog")
    broken_custody_quality = score_industrial_dossier_quality(broken_custody, payload["auditManifest"]["requiredSections"])
    assert broken_custody_quality["status"] == "needs_review"
    assert "chainOfCustodyAuditLog" in broken_custody_quality["missing"]
    broken_calibration = deepcopy(dossier)
    broken_calibration.pop("fieldCalibrationBacktestPlan")
    broken_calibration_quality = score_industrial_dossier_quality(broken_calibration, payload["auditManifest"]["requiredSections"])
    assert broken_calibration_quality["status"] == "needs_review"
    assert "fieldCalibrationBacktestPlan" in broken_calibration_quality["missing"]
    broken_approval = deepcopy(dossier)
    broken_approval.pop("governedApprovalPackage")
    broken_approval_quality = score_industrial_dossier_quality(broken_approval, payload["auditManifest"]["requiredSections"])
    assert broken_approval_quality["status"] == "needs_review"
    assert "governedApprovalPackage" in broken_approval_quality["missing"]
    broken_data_quality = deepcopy(dossier)
    broken_data_quality.pop("dataQualityCalibration")
    broken_data_quality_quality = score_industrial_dossier_quality(broken_data_quality, payload["auditManifest"]["requiredSections"])
    assert broken_data_quality_quality["status"] == "needs_review"
    assert "dataQualityCalibration" in broken_data_quality_quality["missing"]
    broken_telemetry = deepcopy(dossier)
    broken_telemetry.pop("telemetryContract")
    broken_telemetry_quality = score_industrial_dossier_quality(broken_telemetry, payload["auditManifest"]["requiredSections"])
    assert broken_telemetry_quality["status"] == "needs_review"
    assert "telemetryContract" in broken_telemetry_quality["missing"]
    broken_snapshot = deepcopy(dossier)
    broken_snapshot.pop("decisionTelemetrySnapshot")
    broken_snapshot_quality = score_industrial_dossier_quality(broken_snapshot, payload["auditManifest"]["requiredSections"])
    assert broken_snapshot_quality["status"] == "needs_review"
    assert "decisionTelemetrySnapshot" in broken_snapshot_quality["missing"]
    broken_handoff = deepcopy(dossier)
    broken_handoff.pop("fieldExecutionHandoff")
    broken_handoff_quality = score_industrial_dossier_quality(broken_handoff, payload["auditManifest"]["requiredSections"])
    assert broken_handoff_quality["status"] == "needs_review"
    assert "fieldExecutionHandoff" in broken_handoff_quality["missing"]
    broken_runbook = deepcopy(dossier)
    broken_runbook.pop("caseExecutionRunbook")
    broken_runbook_quality = score_industrial_dossier_quality(broken_runbook, payload["auditManifest"]["requiredSections"])
    assert broken_runbook_quality["status"] == "needs_review"
    assert "caseExecutionRunbook" in broken_runbook_quality["missing"]
    broken_closed_loop = deepcopy(dossier)
    broken_closed_loop.pop("closedLoopVerification")
    broken_closed_loop_quality = score_industrial_dossier_quality(broken_closed_loop, payload["auditManifest"]["requiredSections"])
    assert broken_closed_loop_quality["status"] == "needs_review"
    assert "closedLoopVerification" in broken_closed_loop_quality["missing"]
    broken_sensitivity = deepcopy(dossier)
    broken_sensitivity.pop("assumptionSensitivityAnalysis")
    broken_sensitivity_quality = score_industrial_dossier_quality(broken_sensitivity, payload["auditManifest"]["requiredSections"])
    assert broken_sensitivity_quality["status"] == "needs_review"
    assert "assumptionSensitivityAnalysis" in broken_sensitivity_quality["missing"]
    broken_rehearsal = deepcopy(dossier)
    broken_rehearsal.pop("operationalStressRehearsal")
    broken_rehearsal_quality = score_industrial_dossier_quality(broken_rehearsal, payload["auditManifest"]["requiredSections"])
    assert broken_rehearsal_quality["status"] == "needs_review"
    assert "operationalStressRehearsal" in broken_rehearsal_quality["missing"]
    broken_review = deepcopy(dossier)
    broken_review.pop("independentReviewBoard")
    broken_review_quality = score_industrial_dossier_quality(broken_review, payload["auditManifest"]["requiredSections"])
    assert broken_review_quality["status"] == "needs_review"
    assert "independentReviewBoard" in broken_review_quality["missing"]

    packet = run(get_industrial_dossier_packet(case_id))
    assert packet["packetType"] == "industrial_operating_case_packet"
    assert packet["status"] == "ready"
    assert packet["caseHeader"]["sourceConflictId"] == case_id
    assert packet["executiveBrief"]["claim"]
    assert len(packet["approvalChecklist"]) >= 6
    assert all(item["status"] == "pass" for item in packet["approvalChecklist"])
    assert packet["branchProof"]["mode"] == "dossier_three_branch_physical_simulation"
    assert packet["operatingScorecard"]["mode"] == "industrial_operating_scorecard"
    assert packet["operatingScorecard"]["scoreRows"]
    assert packet["machineReadable"]["operatingScorecardReady"] is True
    assert packet["assumptionSensitivityAnalysis"]["mode"] == "industrial_assumption_sensitivity_analysis"
    assert packet["assumptionSensitivityAnalysis"]["stressTests"]
    assert packet["machineReadable"]["assumptionSensitivityReady"] is True
    assert packet["operationalStressRehearsal"]["mode"] == "industrial_operational_stress_rehearsal"
    assert packet["operationalStressRehearsal"]["rehearsalScenarios"]
    assert packet["operationalStressRehearsal"]["escalationTriggers"]
    assert packet["machineReadable"]["operationalStressRehearsalReady"] is True
    assert packet["independentReviewBoard"]["mode"] == "independent_operating_review_board"
    assert packet["independentReviewBoard"]["reviews"]
    assert packet["machineReadable"]["independentReviewReady"] is True
    assert packet["parkRealityModel"]["mode"] == "case_specific_park_reality_model"
    assert packet["parkRealityModel"]["localTopology"]["zones"]
    assert packet["machineReadable"]["parkRealityReady"] is True
    assert packet["liveOperatingSceneModel"]["mode"] == "industrial_live_operating_scene_model"
    assert packet["liveOperatingSceneModel"]["actors"]
    assert packet["liveOperatingSceneModel"]["bottlenecks"]
    assert packet["liveOperatingSceneModel"]["agentBeliefState"]["primaryBelief"]
    assert packet["machineReadable"]["liveOperatingSceneReady"] is True
    assert packet["causalGraph"]["mode"] == "typed_operating_causal_graph"
    assert packet["causalGraph"]["nodes"]
    assert packet["causalGraph"]["edges"]
    assert packet["machineReadable"]["causalGraphReady"] is True
    assert packet["counterfactualReplay"]["mode"] == "counterfactual_branch_replay_matrix"
    assert packet["counterfactualReplay"]["rows"]
    assert packet["machineReadable"]["counterfactualReplayReady"] is True
    assert packet["actionConsequenceSimulation"]["mode"] == "industrial_action_consequence_simulation"
    assert packet["actionConsequenceSimulation"]["consequenceFrames"]
    assert packet["actionConsequenceSimulation"]["branchOutcomeSummary"]
    assert packet["machineReadable"]["actionConsequenceReady"] is True
    assert packet["commercialImpactLedger"]["mode"] == "industrial_commercial_impact_ledger"
    assert packet["commercialImpactLedger"]["rows"]
    assert packet["machineReadable"]["commercialImpactReady"] is True
    assert packet["accessibilityEquityImpact"]["mode"] == "industrial_accessibility_equity_impact"
    assert packet["accessibilityEquityImpact"]["protectedCohorts"]
    assert packet["accessibilityEquityImpact"]["routeAccessChecks"]
    assert packet["machineReadable"]["accessibilityEquityReady"] is True
    assert packet["resourceFeasibilityMatrix"]["mode"] == "industrial_resource_feasibility_matrix"
    assert packet["resourceFeasibilityMatrix"]["receiverExecutionRows"]
    assert packet["resourceFeasibilityMatrix"]["branchFeasibilityComparison"]
    assert packet["machineReadable"]["resourceFeasibilityReady"] is True
    assert packet["policyClauseTrace"]["mode"] == "industrial_policy_clause_trace"
    assert packet["policyClauseTrace"]["clauseRows"]
    assert packet["policyClauseTrace"]["branchPolicyVerdicts"]
    assert packet["machineReadable"]["policyClauseTraceReady"] is True
    assert packet["spatialPhysicsEnvelope"]["mode"] == "industrial_spatial_physics_envelope"
    assert packet["spatialPhysicsEnvelope"]["routePhysics"]
    assert packet["spatialPhysicsEnvelope"]["queueGeometry"]
    assert packet["machineReadable"]["spatialPhysicsReady"] is True
    assert packet["physicalPropagationModel"]["mode"] == "industrial_physical_propagation_model"
    assert packet["physicalPropagationModel"]["chain"]
    assert packet["physicalPropagationModel"]["branchPropagationEffects"]
    assert packet["physicalPropagationModel"]["tripwires"]
    assert packet["machineReadable"]["physicalPropagationReady"] is True
    assert packet["historicalPrecedentMatrix"]["mode"] == "industrial_historical_precedent_matrix"
    assert packet["historicalPrecedentMatrix"]["matchedPrecedents"]
    assert packet["historicalPrecedentMatrix"]["branchPrecedentVerdicts"]
    assert packet["machineReadable"]["historicalPrecedentReady"] is True
    assert packet["guestCommunicationPlan"]["mode"] == "industrial_guest_communication_plan"
    assert packet["guestCommunicationPlan"]["audiencePlans"]
    assert packet["guestCommunicationPlan"]["channelPlan"]
    assert packet["machineReadable"]["guestCommunicationReady"] is True
    assert packet["behavioralResponseModel"]["mode"] == "industrial_behavioral_response_model"
    assert packet["behavioralResponseModel"]["segmentBehavior"]
    assert packet["behavioralResponseModel"]["staffAndReceiverResponse"]
    assert packet["behavioralResponseModel"]["branchBehaviorComparison"]
    assert packet["machineReadable"]["behavioralResponseReady"] is True
    assert packet["operationalConstraintRegister"]["mode"] == "industrial_operational_constraint_register"
    assert packet["operationalConstraintRegister"]["hardConstraints"]
    assert packet["operationalConstraintRegister"]["branchConstraintVerdicts"]
    assert packet["machineReadable"]["operationalConstraintReady"] is True
    assert packet["releaseDecisionRecord"]["mode"] == "industrial_release_decision_record"
    assert packet["releaseDecisionRecord"]["signoffMatrix"]
    assert packet["releaseDecisionRecord"]["postReleaseObligations"]
    assert packet["machineReadable"]["releaseDecisionReady"] is True
    assert packet["releaseAuthorityDecision"]["mode"] == "industrial_release_authority_decision"
    assert packet["releaseAuthorityDecision"]["authorityChecks"]
    assert packet["releaseAuthorityDecision"]["autoExecuteAllowed"] is False
    assert packet["machineReadable"]["releaseAuthorityReady"] is True
    assert packet["machineReadable"]["liveActionAuthorized"] is False
    assert packet["executionReadinessProof"]["mode"] == "industrial_execution_readiness_proof"
    assert packet["executionReadinessProof"]["executionChecks"]
    assert packet["executionReadinessProof"]["readyForLiveExecution"] is False
    assert packet["executionReadinessProof"]["requiredBeforeDispatch"]
    assert packet["machineReadable"]["executionReadinessReady"] is True
    assert packet["releaseRemediationPlan"]["mode"] == "industrial_release_remediation_plan"
    assert packet["releaseRemediationPlan"]["tasks"]
    assert packet["releaseRemediationPlan"]["recheckSequence"]
    assert packet["machineReadable"]["releaseRemediationReady"] is True
    assert packet["operatingProcedureDelta"]["mode"] == "industrial_operating_procedure_delta"
    assert packet["operatingProcedureDelta"]["procedureDeltas"]
    assert packet["operatingProcedureDelta"]["runbookStepUpdates"]
    assert packet["operatingProcedureDelta"]["policyPatchCandidates"]
    assert packet["machineReadable"]["operatingProcedureDeltaReady"] is True
    assert packet["decisionReproducibilityManifest"]["mode"] == "industrial_decision_reproducibility_manifest"
    assert packet["decisionReproducibilityManifest"]["inputArtifacts"]
    assert packet["decisionReproducibilityManifest"]["expectedDeterministicOutputs"]["branchScores"]
    assert packet["decisionReproducibilityManifest"]["replayInstructions"]
    assert packet["machineReadable"]["decisionReproducibilityReady"] is True
    assert packet["chainOfCustodyAuditLog"]["mode"] == "industrial_chain_of_custody_audit_log"
    assert packet["chainOfCustodyAuditLog"]["custodyRows"]
    assert packet["chainOfCustodyAuditLog"]["immutableTraceCheckpoints"]
    assert packet["machineReadable"]["chainOfCustodyReady"] is True
    assert packet["fieldCalibrationBacktestPlan"]["mode"] == "industrial_field_calibration_backtest_plan"
    assert packet["fieldCalibrationBacktestPlan"]["requiredDatasets"]
    assert packet["fieldCalibrationBacktestPlan"]["backtestSuites"]
    assert packet["fieldCalibrationBacktestPlan"]["driftTriggers"]
    assert packet["machineReadable"]["fieldCalibrationBacktestReady"] is True
    assert packet["portfolioContext"]["mode"] == "case_packet_portfolio_context"
    assert packet["portfolioContext"]["portfolioOperatingModel"]["mode"] == "industrial_portfolio_operating_model"
    assert packet["portfolioContext"]["portfolioRiskRanking"]["mode"] == "industrial_portfolio_risk_ranking"
    assert packet["casePortfolioPriority"]["priorityScore"] >= 0
    assert packet["machineReadable"]["portfolioRiskRankingReady"] is True
    assert packet["portfolioContext"]["productionEvidenceGapRegister"]["mode"] == "industrial_production_evidence_gap_register"
    assert packet["caseProductionEvidence"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseProductionEvidence"]["productionReady"] is False
    assert packet["caseProductionEvidence"]["requiredProductionFeeds"]
    assert packet["machineReadable"]["productionEvidenceGapRegisterReady"] is True
    assert packet["portfolioContext"]["fieldReplayValidationHarness"]["mode"] == "industrial_field_replay_validation_harness"
    assert packet["caseFieldReplayValidation"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldReplayValidation"]["validationRuns"]
    assert packet["caseFieldReplayValidation"]["acceptanceGate"]["status"] == "not_field_validated"
    assert packet["machineReadable"]["fieldReplayValidationReady"] is True
    assert packet["portfolioContext"]["capacityCertificationLedger"]["mode"] == "industrial_capacity_certification_ledger"
    assert packet["caseCapacityCertification"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseCapacityCertification"]["capacityFindings"]
    assert packet["caseCapacityCertification"]["pathCertification"]
    assert packet["caseCapacityCertification"]["queueCertification"]
    assert packet["machineReadable"]["capacityCertificationReady"] is True
    assert packet["portfolioContext"]["slaEscalationClock"]["mode"] == "industrial_sla_escalation_clock"
    assert packet["caseSlaEscalation"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseSlaEscalation"]["clockRows"]
    assert packet["caseSlaEscalation"]["nextDeadline"]["deadlineMinutes"] >= 1
    assert packet["machineReadable"]["slaEscalationClockReady"] is True
    assert packet["portfolioContext"]["receiverExecutionContractLedger"]["mode"] == "industrial_receiver_execution_contract_ledger"
    assert packet["caseReceiverExecutionContract"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseReceiverExecutionContract"]["contractRows"]
    assert packet["caseReceiverExecutionContract"]["contractRows"][0]["payloadContract"]["mutationAllowedBeforeApproval"] is False
    assert packet["caseReceiverExecutionContract"]["contractRows"][0]["rollbackContract"]["rollbackTokenRequired"] is True
    assert packet["machineReadable"]["receiverExecutionContractReady"] is True
    assert packet["portfolioContext"]["externalSystemExecutionEvidence"]["mode"] == "industrial_external_system_execution_evidence"
    assert packet["caseExternalExecutionEvidence"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseExternalExecutionEvidence"]["evidenceRows"]
    assert packet["caseExternalExecutionEvidence"]["evidenceRows"][0]["preparedPayload"]["idempotencyKey"]
    assert packet["caseExternalExecutionEvidence"]["evidenceRows"][0]["rollbackEvidence"]["rollbackTokenRequired"] is True
    assert packet["machineReadable"]["externalSystemExecutionEvidenceReady"] is True
    assert packet["portfolioContext"]["industrialDossierCompletenessAudit"]["mode"] == "industrial_dossier_completeness_audit"
    assert packet["caseDossierCompletenessAudit"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseDossierCompletenessAudit"]["proofFamilies"]
    assert packet["caseDossierCompletenessAudit"]["promotionBoundary"]
    assert packet["machineReadable"]["industrialDossierCompletenessAuditReady"] is True
    assert packet["portfolioContext"]["liveEvidenceDriftMonitor"]["mode"] == "industrial_live_evidence_drift_monitor"
    assert packet["caseLiveEvidenceDrift"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseLiveEvidenceDrift"]["liveSignals"]
    assert packet["caseLiveEvidenceDrift"]["requiredRecheck"]
    assert packet["machineReadable"]["liveEvidenceDriftReady"] is True
    assert packet["portfolioContext"]["observedOutcomeCalibrationLedger"]["mode"] == "industrial_observed_outcome_calibration_ledger"
    assert packet["caseObservedOutcomeCalibration"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseObservedOutcomeCalibration"]["variance"]
    assert packet["caseObservedOutcomeCalibration"]["trustDecision"]
    assert packet["machineReadable"]["observedOutcomeCalibrationReady"] is True
    assert packet["portfolioContext"]["varianceRootCauseLedger"]["mode"] == "industrial_variance_root_cause_ledger"
    assert packet["caseVarianceRootCause"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseVarianceRootCause"]["rootCauseRows"]
    assert packet["caseVarianceRootCause"]["reuseDecision"]
    assert packet["machineReadable"]["varianceRootCauseReady"] is True
    assert packet["portfolioContext"]["industrialReviewDispositionLedger"]["mode"] == "industrial_review_disposition_ledger"
    assert packet["caseReviewDisposition"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseReviewDisposition"]["signoffMatrix"]
    assert packet["caseReviewDisposition"]["reviewDisposition"]
    assert packet["machineReadable"]["reviewDispositionReady"] is True
    assert packet["portfolioContext"]["industrialAuditExportManifest"]["mode"] == "industrial_audit_export_manifest"
    assert packet["caseAuditExportPackage"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseAuditExportPackage"]["packageHash"]
    assert packet["caseAuditExportPackage"]["artifactRows"]
    assert packet["machineReadable"]["auditExportManifestReady"] is True
    assert packet["portfolioContext"]["dataLineageCertificationLedger"]["mode"] == "industrial_data_lineage_certification_ledger"
    assert packet["caseDataLineageCertification"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseDataLineageCertification"]["sourceSystemRows"]
    assert packet["caseDataLineageCertification"]["certificationDecision"]
    assert packet["machineReadable"]["dataLineageCertificationReady"] is True
    assert packet["portfolioContext"]["policyRiskControlLedger"]["mode"] == "industrial_policy_risk_control_ledger"
    assert packet["casePolicyRiskControl"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["casePolicyRiskControl"]["controlRows"]
    assert packet["casePolicyRiskControl"]["sensitiveFlags"]
    assert packet["machineReadable"]["policyRiskControlReady"] is True
    assert packet["portfolioContext"]["caseWorkOrderExecutionLedger"]["mode"] == "industrial_case_work_order_execution_ledger"
    assert packet["caseWorkOrderExecution"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseWorkOrderExecution"]["workOrders"]
    assert packet["caseWorkOrderExecution"]["acknowledgementPlan"]
    assert packet["machineReadable"]["caseWorkOrderExecutionReady"] is True
    assert packet["portfolioContext"]["fieldReceiptReconciliationLedger"]["mode"] == "industrial_field_receipt_reconciliation_ledger"
    assert packet["caseFieldReceiptReconciliation"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldReceiptReconciliation"]["receiptRows"]
    assert packet["caseFieldReceiptReconciliation"]["productionBoundary"]
    assert packet["machineReadable"]["fieldReceiptReconciliationReady"] is True
    assert packet["portfolioContext"]["releaseBoardExceptionLedger"]["mode"] == "industrial_release_board_exception_ledger"
    assert packet["caseReleaseBoardException"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseReleaseBoardException"]["exceptionDecision"]
    assert packet["caseReleaseBoardException"]["signoffRows"]
    assert packet["machineReadable"]["releaseBoardExceptionReady"] is True
    assert packet["portfolioContext"]["scenarioCoverageCertificationLedger"]["mode"] == "industrial_scenario_coverage_certification_ledger"
    assert packet["caseScenarioCoverageCertification"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseScenarioCoverageCertification"]["drillFamilyRows"]
    assert packet["caseScenarioCoverageCertification"]["productionBoundary"]
    assert packet["machineReadable"]["scenarioCoverageCertificationReady"] is True
    assert packet["portfolioContext"]["operatorCompetencyEvaluationLedger"]["mode"] == "industrial_operator_competency_evaluation_ledger"
    assert packet["caseOperatorCompetencyEvaluation"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseOperatorCompetencyEvaluation"]["evaluationTasks"]
    assert packet["caseOperatorCompetencyEvaluation"]["scoringRubric"]
    assert packet["machineReadable"]["operatorCompetencyEvaluationReady"] is True
    assert packet["portfolioContext"]["causalEpisodeTrainingLedger"]["mode"] == "industrial_causal_episode_training_ledger"
    assert packet["caseCausalEpisodeTraining"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseCausalEpisodeTraining"]["episodeFrames"]
    assert packet["caseCausalEpisodeTraining"]["physicalProofSummary"]
    assert packet["machineReadable"]["causalEpisodeTrainingReady"] is True
    assert packet["portfolioContext"]["simulationValidityCalibrationLedger"]["mode"] == "industrial_simulation_validity_calibration_ledger"
    assert packet["caseSimulationValidityCalibration"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseSimulationValidityCalibration"]["assumptionRows"]
    assert packet["caseSimulationValidityCalibration"]["falsificationChecks"]
    assert packet["machineReadable"]["simulationValidityCalibrationReady"] is True
    assert packet["portfolioContext"]["fieldObservationProtocolLedger"]["mode"] == "industrial_field_observation_protocol_ledger"
    assert packet["caseFieldObservationProtocol"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldObservationProtocol"]["stationRows"]
    assert packet["caseFieldObservationProtocol"]["measurementProtocol"]
    assert packet["machineReadable"]["fieldObservationProtocolReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceCaptureLedger"]["mode"] == "industrial_field_evidence_capture_ledger"
    assert packet["caseFieldEvidenceCapture"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceCapture"]["formRows"]
    assert packet["caseFieldEvidenceCapture"]["custody"]
    assert packet["machineReadable"]["fieldEvidenceCaptureReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceSampleLedger"]["mode"] == "industrial_field_evidence_sample_ledger"
    assert packet["caseFieldEvidenceSample"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceSample"]["recordRows"]
    assert packet["caseFieldEvidenceSample"]["custodySummary"]
    assert packet["machineReadable"]["fieldEvidenceSampleReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceAdjudicationLedger"]["mode"] == "industrial_field_evidence_adjudication_ledger"
    assert packet["caseFieldEvidenceAdjudication"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceAdjudication"]["metricAdjudications"]
    assert packet["caseFieldEvidenceAdjudication"]["releaseImpact"]
    assert packet["machineReadable"]["fieldEvidenceAdjudicationReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceRemediationLedger"]["mode"] == "industrial_field_evidence_remediation_ledger"
    assert packet["caseFieldEvidenceRemediation"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceRemediation"]["remediationRows"]
    assert packet["caseFieldEvidenceRemediation"]["releaseHold"]
    assert packet["machineReadable"]["fieldEvidenceRemediationReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceRemediationExecutionLedger"]["mode"] == "industrial_field_evidence_remediation_execution_ledger"
    assert packet["caseFieldEvidenceRemediationExecution"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceRemediationExecution"]["executionRows"]
    assert packet["caseFieldEvidenceRemediationExecution"]["holdClearance"]
    assert packet["machineReadable"]["fieldEvidenceRemediationExecutionReady"] is True
    assert packet["portfolioContext"]["fieldEvidenceReleaseClearanceLedger"]["mode"] == "industrial_field_evidence_release_clearance_ledger"
    assert packet["caseFieldEvidenceReleaseClearance"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldEvidenceReleaseClearance"]["signoffMatrix"]
    assert packet["caseFieldEvidenceReleaseClearance"]["clearancePacket"]
    assert packet["machineReadable"]["fieldEvidenceReleaseClearanceReady"] is True
    assert packet["portfolioContext"]["spatialExecutionDrillLedger"]["mode"] == "industrial_spatial_execution_drill_ledger"
    assert packet["caseSpatialExecutionDrill"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseSpatialExecutionDrill"]["drillFrames"]
    assert packet["caseSpatialExecutionDrill"]["stopRules"]
    assert packet["caseSpatialExecutionDrill"]["drillPacket"]
    assert packet["machineReadable"]["spatialExecutionDrillReady"] is True
    assert packet["portfolioContext"]["observedDrillVarianceLedger"]["mode"] == "industrial_observed_drill_variance_ledger"
    assert packet["caseObservedDrillVariance"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseObservedDrillVariance"]["varianceRows"]
    assert packet["caseObservedDrillVariance"]["reuseGate"]
    assert packet["caseObservedDrillVariance"]["variancePacket"]
    assert packet["machineReadable"]["observedDrillVarianceReady"] is True
    assert packet["portfolioContext"]["industrialAcceptanceCertificationLedger"]["mode"] == "industrial_acceptance_certification_ledger"
    assert packet["caseIndustrialAcceptanceCertification"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseIndustrialAcceptanceCertification"]["proofFamilyRows"]
    assert packet["caseIndustrialAcceptanceCertification"]["signoffPosture"]
    assert packet["caseIndustrialAcceptanceCertification"]["certificationPacket"]
    assert packet["machineReadable"]["industrialAcceptanceCertificationReady"] is True
    assert packet["portfolioContext"]["productionEvidenceAcquisitionLedger"]["mode"] == "industrial_production_evidence_acquisition_ledger"
    assert packet["caseProductionEvidenceAcquisition"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseProductionEvidenceAcquisition"]["feedAcquisitions"]
    assert packet["caseProductionEvidenceAcquisition"]["graduationStages"]
    assert packet["caseProductionEvidenceAcquisition"]["acquisitionPacket"]
    assert packet["machineReadable"]["productionEvidenceAcquisitionReady"] is True
    assert packet["portfolioContext"]["productionDataIngestionContract"]["mode"] == "industrial_production_data_ingestion_contract"
    assert packet["caseProductionDataContract"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseProductionDataContract"]["feedContracts"]
    assert packet["caseProductionDataContract"]["graduationCriteria"]
    assert packet["machineReadable"]["productionDataIngestionContractReady"] is True
    assert packet["portfolioContext"]["industrialPromotionCertificationGate"]["mode"] == "industrial_promotion_certification_gate"
    assert packet["casePromotionCertification"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["casePromotionCertification"]["certificationChecks"]
    assert packet["casePromotionCertification"]["releaseBoundary"]
    assert packet["machineReadable"]["promotionCertificationGateReady"] is True
    assert packet["portfolioContext"]["fieldTrialProtocolLedger"]["mode"] == "industrial_field_trial_protocol_ledger"
    assert packet["caseFieldTrialProtocol"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldTrialProtocol"]["trialScope"]
    assert packet["caseFieldTrialProtocol"]["stopRules"]
    assert packet["machineReadable"]["fieldTrialProtocolReady"] is True
    assert packet["portfolioContext"]["fieldTrialExecutionEvidenceLedger"]["mode"] == "industrial_field_trial_execution_evidence_ledger"
    assert packet["caseFieldTrialExecutionEvidence"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldTrialExecutionEvidence"]["observationCaptures"]
    assert packet["caseFieldTrialExecutionEvidence"]["trialOutcomeDisposition"]
    assert packet["machineReadable"]["fieldTrialExecutionEvidenceReady"] is True
    assert packet["portfolioContext"]["fieldTrialCloseoutLedger"]["mode"] == "industrial_field_trial_closeout_ledger"
    assert packet["caseFieldTrialCloseout"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFieldTrialCloseout"]["trialResultRecord"]
    assert packet["caseFieldTrialCloseout"]["promotionDecision"]
    assert packet["machineReadable"]["fieldTrialCloseoutReady"] is True
    assert packet["portfolioContext"]["industrialOperatingTimelineLedger"]["mode"] == "industrial_operating_timeline_ledger"
    assert packet["caseOperatingTimeline"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseOperatingTimeline"]["eventRows"]
    assert packet["caseOperatingTimeline"]["mapBindingSummary"]
    assert packet["machineReadable"]["operatingTimelineReady"] is True
    assert packet["portfolioContext"]["incidentCommandDecisionLog"]["mode"] == "industrial_incident_command_decision_log"
    assert packet["caseIncidentCommandDecision"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseIncidentCommandDecision"]["commandRoles"]["commander"]
    assert packet["caseIncidentCommandDecision"]["decisionRecord"]["decision"]
    assert packet["caseIncidentCommandDecision"]["auditEvent"]["auditId"]
    assert packet["machineReadable"]["incidentCommandDecisionLogReady"] is True
    assert packet["portfolioContext"]["industrialActionReplayLedger"]["mode"] == "industrial_action_replay_ledger"
    assert packet["caseIndustrialActionReplay"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseIndustrialActionReplay"]["timelineFrames"]
    assert packet["caseIndustrialActionReplay"]["closedLoopWatch"]
    assert packet["machineReadable"]["industrialActionReplayReady"] is True
    assert packet["portfolioContext"]["physicalMovementProofLedger"]["mode"] == "industrial_physical_movement_proof_ledger"
    assert packet["casePhysicalMovementProof"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["casePhysicalMovementProof"]["mapObjectBinding"]
    assert packet["casePhysicalMovementProof"]["pathProofRows"]
    assert packet["casePhysicalMovementProof"]["queueProofRows"]
    assert packet["machineReadable"]["physicalMovementProofReady"] is True
    assert packet["portfolioContext"]["telemetryAcceptanceLedger"]["mode"] == "industrial_telemetry_acceptance_ledger"
    assert packet["caseTelemetryAcceptance"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseTelemetryAcceptance"]["acceptanceGateRows"]
    assert packet["caseTelemetryAcceptance"]["sourceContract"]["sourceBindingCount"] >= 1
    assert packet["caseTelemetryAcceptance"]["closedLoopAcceptance"]
    assert packet["machineReadable"]["telemetryAcceptanceReady"] is True
    assert packet["portfolioContext"]["outcomeAccountabilityLedger"]["mode"] == "industrial_outcome_accountability_ledger"
    assert packet["caseOutcomeAccountability"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseOutcomeAccountability"]["expectedOutcome"]
    assert packet["caseOutcomeAccountability"]["observedEvidenceStatus"]
    assert packet["caseOutcomeAccountability"]["rollbackPosture"]["armed"] is True
    assert packet["machineReadable"]["outcomeAccountabilityReady"] is True
    assert packet["portfolioContext"]["industrialCaseFileSynthesis"]["mode"] == "industrial_case_file_synthesis"
    assert packet["caseFile"]["caseId"] == packet["caseHeader"]["id"]
    assert packet["caseFile"]["caseNarrative"]["nextOperatorStep"]
    assert packet["caseFile"]["proofStack"]["timelineFrameCount"] >= 1
    assert packet["machineReadable"]["industrialCaseFileReady"] is True
    assert packet["portfolioContext"]["portfolioOperatingModel"]["assetInventory"]["zones"] >= 5
    assert packet["portfolioContext"]["portfolioOperatingModel"]["spatialNetwork"]["bottlenecks"]
    assert packet["portfolioContext"]["portfolioOperatingModel"]["coverageReadiness"]["coverageGaps"] == []
    assert packet["portfolioContext"]["industrialStandardsMatrix"]["mode"] == "industrial_standards_matrix"
    assert packet["portfolioContext"]["industrialDeploymentReadiness"]["deploymentState"] == "demo_ready_not_production_ready"
    assert packet["portfolioContext"]["industrialOwnershipModel"]["mode"] == "industrial_ownership_raci_model"
    assert packet["portfolioContext"]["caseDomainCoverage"]["domain"] == packet["caseHeader"]["domain"]
    assert packet["machineReadable"]["portfolioContextReady"] is True
    assert packet["industrialStandardsMatrix"]["mode"] == "industrial_standards_matrix"
    assert packet["industrialStandardsMatrix"]["summary"]["status"] == "ready"
    assert packet["machineReadable"]["industrialStandardsReady"] is True
    assert packet["industrialDeploymentReadiness"]["mode"] == "industrial_deployment_readiness"
    assert packet["industrialDeploymentReadiness"]["summary"]["productionReady"] is False
    assert packet["industrialDeploymentReadiness"]["productionBlockers"]
    assert packet["machineReadable"]["deploymentReadinessReady"] is True
    assert packet["industrialOwnershipModel"]["mode"] == "industrial_ownership_raci_model"
    assert packet["industrialOwnershipModel"]["domainRaci"]
    assert packet["machineReadable"]["ownershipModelReady"] is True
    assert packet["spatialProof"]["mode"] == "map_object_causality_trace"
    assert packet["spatialProof"]["zones"]
    assert packet["spatialProof"]["paths"]
    assert packet["spatialProof"]["queues"]
    assert packet["machineReadable"]["spatialProofReady"] is True
    assert packet["mapObjectEvidenceIndex"]["mode"] == "industrial_map_object_evidence_index"
    assert packet["mapObjectEvidenceIndex"]["objectRows"]
    assert packet["mapObjectEvidenceIndex"]["pathRows"]
    assert packet["mapObjectEvidenceIndex"]["queueRows"]
    assert packet["machineReadable"]["mapObjectEvidenceReady"] is True
    assert packet["approvalPackage"]["mode"] == "governed_operator_approval_package"
    assert packet["approvalPackage"]["receiverWrites"]
    assert packet["approvalPackage"]["authorityBoundary"]["autoExecuteAllowed"] is False
    assert packet["machineReadable"]["approvalPackageReady"] is True
    assert packet["dataQualityCalibration"]["mode"] == "industrial_data_quality_calibration"
    assert packet["dataQualityCalibration"]["confidenceScore"] >= 70
    assert packet["machineReadable"]["dataQualityReady"] is True
    assert packet["telemetryContract"]["mode"] == "industrial_case_telemetry_contract"
    assert packet["telemetryContract"]["sourceBindings"]
    assert packet["machineReadable"]["telemetryContractReady"] is True
    assert packet["fieldSignalReconciliation"]["mode"] == "industrial_field_signal_reconciliation"
    assert packet["fieldSignalReconciliation"]["sourceRows"]
    assert packet["fieldSignalReconciliation"]["crossChecks"]
    assert packet["machineReadable"]["fieldSignalReconciliationReady"] is True
    assert packet["decisionTelemetrySnapshot"]["mode"] == "industrial_decision_telemetry_snapshot"
    assert packet["decisionTelemetrySnapshot"]["queueRows"]
    assert packet["decisionTelemetrySnapshot"]["thresholdBreaches"]
    assert packet["decisionTelemetrySnapshot"]["sourceLineage"]["requiredForProduction"]
    assert packet["decisionTelemetrySnapshot"]["productionAcceptanceGates"]
    assert packet["decisionTelemetrySnapshot"]["telemetryCertification"]["certificationStatus"] == "demo_ready_not_production_certified"
    assert packet["decisionTelemetrySnapshot"]["queueRows"][0]["sourceIdentity"]["sourcePath"]
    assert packet["machineReadable"]["decisionTelemetrySnapshotReady"] is True
    assert packet["machineReadable"]["decisionTelemetryProductionReady"] is False
    assert packet["fieldExecutionHandoff"]["mode"] == "industrial_field_execution_handoff"
    assert packet["fieldExecutionHandoff"]["dispatches"]
    assert packet["machineReadable"]["fieldExecutionHandoffReady"] is True
    assert packet["caseExecutionRunbook"]["mode"] == "industrial_case_execution_runbook"
    assert packet["caseExecutionRunbook"]["lifecycle"]
    assert packet["machineReadable"]["runbookReady"] is True
    assert packet["closedLoopVerification"]["mode"] == "closed_loop_verification_plan"
    assert packet["closedLoopVerification"]["observationWindows"]
    assert packet["machineReadable"]["closedLoopReady"] is True
    assert packet["branchProof"]["selectedBranch"] in {"no_action", "fast_local_action", "governed_agent_action"}
    assert {branch["id"] for branch in packet["branchProof"]["branches"]} == {"no_action", "fast_local_action", "governed_agent_action"}
    assert all(branch["deltaFromNow"] for branch in packet["branchProof"]["branches"])
    assert all(branch["physicalImpact"]["physicalDeltas"] for branch in packet["branchProof"]["branches"])
    assert packet["branchPhysicalImpactMatrix"]["mode"] == "industrial_branch_physical_impact_matrix"
    assert packet["machineReadable"]["branchPhysicalImpactReady"] is True
    assert all(row["simulationVerdict"] for row in packet["actionTrainingFrame"])
    assert packet["machineReadable"]["branchProofReady"] is True
    assert packet["machineReadable"]["provenanceSourceCount"] >= 4
    assert packet["integrity"]["algorithm"] == "sha256"
    assert packet["integrity"]["packetId"].startswith("packet_")
    assert len(packet["integrity"]["packetHash"]) == 64
    assert len(packet["integrity"]["evidenceHash"]) == 64
    assert packet["machineReadable"]["packetHash"] == packet["integrity"]["packetHash"]
    assert packet["verification"]["qualityGate"]["readyThreshold"] == 90
