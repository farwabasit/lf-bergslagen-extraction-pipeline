package se.lfbergslagen.csservice.store;

import org.springframework.stereotype.Component;
import se.lfbergslagen.csservice.model.ChatMessage;
import se.lfbergslagen.csservice.model.ChatRequest;
import se.lfbergslagen.csservice.model.ChatRequestStatus;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory store of "talk to a person" hand-offs from the AI assistant.
 * Keyed by the assistant's chat session id.
 */
@Component
public class ChatRequestStore {

    private final Map<String, ChatRequest> requests = new ConcurrentHashMap<>();

    public ChatRequest createOrUpdate(String sessionId, String customerSummary, List<ChatMessage> transcript) {
        ChatRequest request = requests.computeIfAbsent(sessionId, id -> {
            ChatRequest r = new ChatRequest();
            r.setSessionId(id);
            return r;
        });
        request.setCustomerSummary(customerSummary);
        request.setTranscript(transcript);
        if (request.getStatus() == ChatRequestStatus.CLOSED) {
            request.setStatus(ChatRequestStatus.PENDING);
        }
        return request;
    }

    public Optional<ChatRequest> get(String sessionId) {
        return Optional.ofNullable(requests.get(sessionId));
    }

    public Collection<ChatRequest> list() {
        return requests.values();
    }
}
