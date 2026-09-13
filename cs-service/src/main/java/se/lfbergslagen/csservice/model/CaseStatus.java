package se.lfbergslagen.csservice.model;

public enum CaseStatus {
    NEW,
    IN_PROGRESS,
    /** Customer Service Rep has finished intake/triage and handed the case
     * to Operations for execution - used for FRAUD/DISPUTE cases, which
     * (unlike mortgage review) stay the same case rather than spawning a
     * new one when handed off. */
    SUBMITTED,
    RESOLVED
}
