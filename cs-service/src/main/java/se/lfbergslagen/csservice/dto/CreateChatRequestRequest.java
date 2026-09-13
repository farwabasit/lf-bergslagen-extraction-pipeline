package se.lfbergslagen.csservice.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import se.lfbergslagen.csservice.model.ChatMessage;

import java.util.List;

public class CreateChatRequestRequest {

    @NotBlank
    private String sessionId;

    private String customerSummary;

    @NotEmpty
    private List<ChatMessage> transcript;

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
        this.transcript = transcript;
    }
}
