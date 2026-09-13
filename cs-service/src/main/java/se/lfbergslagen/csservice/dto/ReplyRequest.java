package se.lfbergslagen.csservice.dto;

import jakarta.validation.constraints.NotBlank;

public class ReplyRequest {

    @NotBlank
    private String agent;

    @NotBlank
    private String message;

    public String getAgent() {
        return agent;
    }

    public void setAgent(String agent) {
        this.agent = agent;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }
}
