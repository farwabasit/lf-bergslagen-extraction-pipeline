package se.lfbergslagen.csservice.dto;

import jakarta.validation.constraints.NotNull;
import se.lfbergslagen.csservice.model.CaseStatus;

public class UpdateStatusRequest {

    @NotNull
    private CaseStatus status;

    public CaseStatus getStatus() {
        return status;
    }

    public void setStatus(CaseStatus status) {
        this.status = status;
    }
}
