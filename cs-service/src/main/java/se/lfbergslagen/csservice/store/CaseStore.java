package se.lfbergslagen.csservice.store;

import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Component;
import se.lfbergslagen.csservice.model.Case;
import se.lfbergslagen.csservice.model.CaseStatus;
import se.lfbergslagen.csservice.model.CaseType;

import java.security.SecureRandom;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory case store - this is a demo workflow app, not backed by a real
 * database. Data resets whenever the service restarts.
 */
@Component
public class CaseStore {

    private final Map<String, Case> cases = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();

    public Case create(CaseType type, String customerName, String customerId, String description, Map<String, String> extra) {
        Case c = new Case();
        c.setId(generateId());
        c.setType(type);
        c.setStatus(CaseStatus.NEW);
        c.setCustomerName(customerName);
        c.setCustomerId(customerId);
        c.setDescription(description);
        c.setExtra(extra != null ? new LinkedHashMap<>(extra) : new LinkedHashMap<>());
        cases.put(c.getId(), c);
        return c;
    }

    public Optional<Case> get(String id) {
        return Optional.ofNullable(cases.get(id));
    }

    public Collection<Case> list() {
        return cases.values();
    }

    private String generateId() {
        String id;
        do {
            id = "CASE-" + (100000 + random.nextInt(900000));
        } while (cases.containsKey(id));
        return id;
    }

    /** Seed data so a customer can ask about an ongoing mortgage application
     * by ID in a demo without first having created one. */
    @PostConstruct
    public void seed() {
        Case mortgage = new Case();
        mortgage.setId("CASE-700001");
        mortgage.setType(CaseType.MORTGAGE_APPLICATION);
        mortgage.setStatus(CaseStatus.IN_PROGRESS);
        mortgage.setCustomerName("Anna Andersson");
        mortgage.setCustomerId("CUST-1001");
        mortgage.setDescription("Mortgage application for an apartment purchase in Örebro.");
        mortgage.setAssignedAgent("Björn Lindqvist (Loan Officer)");
        Map<String, String> extra = new LinkedHashMap<>();
        extra.put("loanAmount", "2,400,000 SEK");
        extra.put("nextStep", "Awaiting property valuation report");
        mortgage.setExtra(extra);
        cases.put(mortgage.getId(), mortgage);

        Case mortgage2 = new Case();
        mortgage2.setId("CASE-700002");
        mortgage2.setType(CaseType.MORTGAGE_APPLICATION);
        mortgage2.setStatus(CaseStatus.RESOLVED);
        mortgage2.setCustomerName("Erik Svensson");
        mortgage2.setCustomerId("CUST-1002");
        mortgage2.setDescription("Mortgage application for a house purchase in Karlskoga.");
        mortgage2.setAssignedAgent("Björn Lindqvist (Loan Officer)");
        Map<String, String> extra2 = new LinkedHashMap<>();
        extra2.put("loanAmount", "3,100,000 SEK");
        extra2.put("nextStep", "Approved - funds disbursed");
        mortgage2.setExtra(extra2);
        cases.put(mortgage2.getId(), mortgage2);
    }
}
