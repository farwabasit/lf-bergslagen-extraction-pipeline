package se.lfbergslagen.csservice.model;

public enum CsRole {
    /** Responds to live chat hand-offs from the AI assistant and guides the customer. */
    CS_REP,
    /** Picks up cases the AI agents route for a human decision (fraud, dispute,
     * callback, mortgage application/review). */
    ADVISOR,
    /** Picks up fulfilment/execution tasks once an agent or an Advisor has
     * decided - e-signature, account opening, disbursement. */
    OPERATIONS
}
