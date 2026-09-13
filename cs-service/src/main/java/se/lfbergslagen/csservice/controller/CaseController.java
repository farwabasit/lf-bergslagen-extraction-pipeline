package se.lfbergslagen.csservice.controller;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import se.lfbergslagen.csservice.dto.CreateCaseRequest;
import se.lfbergslagen.csservice.dto.PickupRequest;
import se.lfbergslagen.csservice.dto.UpdateStatusRequest;
import se.lfbergslagen.csservice.model.Case;
import se.lfbergslagen.csservice.model.CaseStatus;
import se.lfbergslagen.csservice.model.CaseType;
import se.lfbergslagen.csservice.model.CsRole;
import se.lfbergslagen.csservice.model.RolePermissions;
import se.lfbergslagen.csservice.store.CaseStore;

import java.util.Collection;
import java.util.Optional;

/**
 * Case queue for Customer Service Reps, Advisors, and Operations. Every
 * mutating (and, for defense in depth, every reading) endpoint here
 * requires an X-CS-Role header and enforces it server-side via
 * RolePermissions - a UI that hides a button is only a convenience; this is
 * what actually stops a role from touching a case outside its remit.
 *
 * FRAUD/DISPUTE cases move CS_REP -> OPERATIONS: a Rep gathers details
 * first, then submits, then Operations can process. RolePermissions blocks
 * Operations from acting on (or even seeing) one that hasn't been submitted
 * yet - a 409, distinct from the 403 used for "wrong role entirely".
 *
 * /api/cases (create) is the one exception: that's called by the AI
 * assistant backend, not by a human agent, so it isn't role-gated.
 */
@RestController
@RequestMapping("/api/cases")
public class CaseController {

    private final CaseStore caseStore;

    public CaseController(CaseStore caseStore) {
        this.caseStore = caseStore;
    }

    private CsRole requireRole(String roleHeader) {
        if (roleHeader == null || roleHeader.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Missing X-CS-Role header.");
        }
        try {
            return CsRole.valueOf(roleHeader.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown role '" + roleHeader + "'.");
        }
    }

    private boolean isVisibleTo(CsRole role, Case c) {
        if (!RolePermissions.canActOnCase(role, c.getType())) {
            return false;
        }
        if (role == CsRole.OPERATIONS) {
            return RolePermissions.canOperationsProcessNow(c.getType(), c.getStatus());
        }
        return true;
    }

    private void requireCaseAccess(CsRole role, Case c) {
        if (!RolePermissions.canActOnCase(role, c.getType())) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    role + " is not authorized for " + c.getType() + " cases."
            );
        }
        if (role == CsRole.OPERATIONS && !RolePermissions.canOperationsProcessNow(c.getType(), c.getStatus())) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "This case is still with Customer Service and hasn't been submitted to Operations yet."
            );
        }
    }

    @PostMapping
    public ResponseEntity<Case> create(@Valid @RequestBody CreateCaseRequest request) {
        Case created = caseStore.create(
                request.getType(),
                request.getCustomerName(),
                request.getCustomerId(),
                request.getDescription(),
                request.getExtra()
        );
        return ResponseEntity.ok(created);
    }

    @GetMapping
    public Collection<Case> list(
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader,
            @RequestParam(required = false) CaseStatus status,
            @RequestParam(required = false) CaseType type
    ) {
        CsRole role = requireRole(roleHeader);
        return caseStore.list().stream()
                .filter(c -> isVisibleTo(role, c))
                .filter(c -> status == null || c.getStatus() == status)
                .filter(c -> type == null || c.getType() == type)
                .sorted((a, b) -> b.getCreatedAt().compareTo(a.getCreatedAt()))
                .toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<Case> get(
            @PathVariable String id,
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader
    ) {
        CsRole role = requireRole(roleHeader);
        Optional<Case> found = caseStore.get(id);
        found.ifPresent(c -> requireCaseAccess(role, c));
        return found.map(ResponseEntity::ok).orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/pickup")
    public ResponseEntity<Case> pickup(
            @PathVariable String id,
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader,
            @Valid @RequestBody PickupRequest request
    ) {
        CsRole role = requireRole(roleHeader);
        return caseStore.get(id)
                .map(c -> {
                    requireCaseAccess(role, c);
                    c.setAssignedAgent(request.getAgent());
                    c.setStatus(CaseStatus.IN_PROGRESS);
                    return ResponseEntity.ok(c);
                })
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/status")
    public ResponseEntity<Case> updateStatus(
            @PathVariable String id,
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader,
            @Valid @RequestBody UpdateStatusRequest request
    ) {
        CsRole role = requireRole(roleHeader);
        return caseStore.get(id)
                .map(c -> {
                    requireCaseAccess(role, c);
                    c.setStatus(request.getStatus());
                    return ResponseEntity.ok(c);
                })
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    /**
     * Customer Service Rep hand-off point for FRAUD/DISPUTE: marks the case
     * SUBMITTED once the Rep has gathered the details, which is what makes
     * it visible/actionable to Operations (see canOperationsProcessNow).
     * Unlike the mortgage hand-off below, this is the SAME case moving
     * queues, not a new one - fraud/dispute has no separate "operations
     * case type" the way mortgage does.
     */
    @PostMapping("/{id}/submit-to-operations")
    public ResponseEntity<Case> submitToOperations(
            @PathVariable String id,
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader,
            @Valid @RequestBody PickupRequest request
    ) {
        CsRole role = requireRole(roleHeader);
        if (role != CsRole.CS_REP) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Only CS_REP may submit a case to Operations.");
        }
        return caseStore.get(id)
                .map(c -> {
                    if (c.getType() != CaseType.FRAUD && c.getType() != CaseType.DISPUTE) {
                        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Only FRAUD/DISPUTE cases can be submitted to Operations this way.");
                    }
                    c.setAssignedAgent(request.getAgent());
                    c.setStatus(CaseStatus.SUBMITTED);
                    return ResponseEntity.ok(c);
                })
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    /**
     * Closes the loop the Advisor role's remit ends at: once an Advisor has
     * finished a MORTGAGE_REVIEW case, this resolves it and creates the
     * follow-on MORTGAGE_OPERATIONS case for Operations to pick up -
     * "agent triggers -> Advisor decides -> Operations executes".
     */
    @PostMapping("/{id}/approve-to-operations")
    public ResponseEntity<?> approveToOperations(
            @PathVariable String id,
            @RequestHeader(value = "X-CS-Role", required = false) String roleHeader,
            @Valid @RequestBody PickupRequest request
    ) {
        CsRole role = requireRole(roleHeader);
        if (role != CsRole.ADVISOR) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Only ADVISOR may approve a case to Operations.");
        }
        Optional<Case> found = caseStore.get(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        Case reviewCase = found.get();
        if (reviewCase.getType() != CaseType.MORTGAGE_REVIEW) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Only MORTGAGE_REVIEW cases can be approved to Operations.");
        }

        reviewCase.setStatus(CaseStatus.RESOLVED);
        reviewCase.setAssignedAgent(request.getAgent());

        Case opsCase = caseStore.create(
                CaseType.MORTGAGE_OPERATIONS,
                reviewCase.getCustomerName(),
                reviewCase.getCustomerId(),
                "Approved by Advisor (" + request.getAgent() + ") following manual review of case " + reviewCase.getId()
                        + ". Next: e-signature, account opening, disbursement.",
                reviewCase.getExtra()
        );

        return ResponseEntity.ok(new ApproveToOperationsResult(reviewCase, opsCase));
    }

    public record ApproveToOperationsResult(Case reviewCase, Case operationsCase) {
    }
}
