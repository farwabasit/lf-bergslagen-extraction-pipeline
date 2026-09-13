package se.lfbergslagen.csservice.model;

import java.util.EnumSet;
import java.util.Set;

/**
 * Which case types each role may see and act on, and whether a role may
 * touch chat hand-offs at all. This is authorization, not authentication -
 * the caller's role is a self-declared header (X-CS-Role), not a verified
 * login. That's a real limitation for a demo with no user accounts; see the
 * README/handover notes. What this DOES genuinely provide is server-side
 * enforcement: the frontend hiding a tab is only a convenience, the API
 * itself refuses actions outside a role's remit regardless of what the
 * client sends.
 *
 * FRAUD and DISPUTE are jointly owned by CS_REP and OPERATIONS, in sequence:
 * a Customer Service Rep picks it up and gathers details first (status NEW /
 * IN_PROGRESS), then submits it (status SUBMITTED) for Operations to
 * process. OPERATIONS is authorized for the case TYPE but additionally
 * gated by STATUS - see canOperationsProcessNow - so Operations can't jump
 * a case that's still with the Rep.
 */
public final class RolePermissions {

    private RolePermissions() {
    }

    private static final Set<CaseType> ADVISOR_CASE_TYPES = EnumSet.of(
            CaseType.CALLBACK,
            CaseType.MORTGAGE_APPLICATION,
            CaseType.MORTGAGE_REVIEW,
            CaseType.OTHER
    );

    private static final Set<CaseType> CS_REP_CASE_TYPES = EnumSet.of(
            CaseType.FRAUD,
            CaseType.DISPUTE
    );

    private static final Set<CaseType> OPERATIONS_CASE_TYPES = EnumSet.of(
            CaseType.MORTGAGE_OPERATIONS,
            CaseType.FRAUD,
            CaseType.DISPUTE
    );

    /** Case types Operations may only touch once SUBMITTED by CS_REP first. */
    private static final Set<CaseType> OPERATIONS_REQUIRES_SUBMISSION = EnumSet.of(
            CaseType.FRAUD,
            CaseType.DISPUTE
    );

    public static Set<CaseType> caseTypesFor(CsRole role) {
        return switch (role) {
            case ADVISOR -> ADVISOR_CASE_TYPES;
            case CS_REP -> CS_REP_CASE_TYPES;
            case OPERATIONS -> OPERATIONS_CASE_TYPES;
        };
    }

    public static boolean canActOnCase(CsRole role, CaseType type) {
        return caseTypesFor(role).contains(type);
    }

    /** Additional check on top of canActOnCase, for roles/types where
     * authorization to the TYPE isn't enough - Operations also needs the
     * case to have actually reached them yet. */
    public static boolean canOperationsProcessNow(CaseType type, CaseStatus status) {
        if (!OPERATIONS_REQUIRES_SUBMISSION.contains(type)) {
            return true;
        }
        return status == CaseStatus.SUBMITTED || status == CaseStatus.RESOLVED;
    }

    public static boolean canHandleChatRequests(CsRole role) {
        return role == CsRole.CS_REP;
    }
}
