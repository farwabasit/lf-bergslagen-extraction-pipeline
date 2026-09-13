package se.lfbergslagen.csservice.dto;

import jakarta.validation.constraints.NotBlank;

public class PickupRequest {

    @NotBlank
    private String agent;

    public String getAgent() {
        return agent;
    }

    public void setAgent(String agent) {
        this.agent = agent;
    }
}
