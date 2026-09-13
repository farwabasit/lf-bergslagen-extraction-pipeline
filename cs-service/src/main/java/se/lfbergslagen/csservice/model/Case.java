package se.lfbergslagen.csservice.model;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A customer service case (callback request, fraud report, transaction
 * dispute, mortgage application status, ...). In-memory only - this is a
 * demo workflow app, not backed by a real database.
 */
public class Case {

    private String id;
    private CaseType type;
    private CaseStatus status = CaseStatus.NEW;
    private String customerName;
    private String customerId;
    private String description;
    private String assignedAgent;
    private Instant createdAt = Instant.now();
    private Instant updatedAt = Instant.now();
    private Map<String, String> extra = new LinkedHashMap<>();

    public Case() {
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public CaseType getType() {
        return type;
    }

    public void setType(CaseType type) {
        this.type = type;
    }

    public CaseStatus getStatus() {
        return status;
    }

    public void setStatus(CaseStatus status) {
        this.status = status;
        this.updatedAt = Instant.now();
    }

    public String getCustomerName() {
        return customerName;
    }

    public void setCustomerName(String customerName) {
        this.customerName = customerName;
    }

    public String getCustomerId() {
        return customerId;
    }

    public void setCustomerId(String customerId) {
        this.customerId = customerId;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public String getAssignedAgent() {
        return assignedAgent;
    }

    public void setAssignedAgent(String assignedAgent) {
        this.assignedAgent = assignedAgent;
        this.updatedAt = Instant.now();
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }

    public Map<String, String> getExtra() {
        return extra;
    }

    public void setExtra(Map<String, String> extra) {
        this.extra = extra != null ? extra : new LinkedHashMap<>();
    }
}
