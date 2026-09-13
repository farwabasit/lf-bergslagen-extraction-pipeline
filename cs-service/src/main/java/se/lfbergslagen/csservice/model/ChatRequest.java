package se.lfbergslagen.csservice.model;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * A "talk to a person" hand-off from the AI assistant: the full chat
 * transcript that happened before the customer asked for a human, so the CS
 * agent doesn't have to ask the customer to repeat themselves.
 */
public class ChatRequest {

    private String sessionId;
    private String customerSummary;
    private List<ChatMessage> transcript = new ArrayList<>();
    private ChatRequestStatus status = ChatRequestStatus.PENDING;
    private String assignedAgent;
    private Instant createdAt = Instant.now();
    private Instant updatedAt = Instant.now();

    public ChatRequest() {
    }

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }

    public String getCustomerSummary() {
        return customerSummary;
    }

    public void setCustomerSummary(String customerSummary) {
        this.customerSummary = customerSummary;
    }

    public List<ChatMessage> getTranscript() {
        return transcript;
    }

    public void setTranscript(List<ChatMessage> transcript) {
        this.transcript = transcript != null ? transcript : new ArrayList<>();
    }

    public ChatRequestStatus getStatus() {
        return status;
    }

    public void setStatus(ChatRequestStatus status) {
        this.status = status;
        this.updatedAt = Instant.now();
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
}
