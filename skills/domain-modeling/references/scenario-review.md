# Scenario review

Load for ambiguous language, uncertain cardinality or a code/model contradiction. Use scenarios to distinguish meanings, not to obtain agreement by assertion.

## Probe the boundary

For each disputed claim, record current definition/source, competing interpretation, discriminating example and outcome (agreed or unresolved). Ask only probes that bear on the session's question:

| Dispute | Concrete probe | Evidence to retain |
| --- | --- | --- |
| Overloaded term | “When support says account, is that the buyer organization or the login identity? Can two logins buy for one organization?” | Context ownership and distinct canonical names, or unresolved alternatives |
| Cardinality | “Can this have none? Exactly one? More than one? What about the reverse direction?” | Min/max in both directions and lifecycle scope |
| Quantity vs identity | “There are two lines; the first has quantity three. Cancelling one unit changes which object and count?” | Line count, unit count and remaining quantity kept distinct |
| Lifecycle | “Can another cancellation follow the first? Can fulfilled units be cancelled, or are they returned?” | Accepted preconditions and postconditions; unknowns stay unknown |
| Context boundary | “Does cancelling an unbilled quantity create a Billing object? What if it was already invoiced?” | Separate business concepts and agreed cross-context relation |
| Code/model conflict | “The owner permits a one-unit cancellation, but this method changes the whole order status. Which rule is authoritative?” | Specific source, domain claim, divergent scenario and disposition |

Avoid inventing answers to these questions. An existing approved rule can settle a probe; a suggestive class name or a test for a different case cannot.

## Worked ordering/billing case

The following is synthetic, inspectable example data, not a claimed execution or a universal commerce model.

### Existing state

The repository's `docs/agents/domain.md` routes through root `CONTEXT-MAP.md` to `src/ordering/CONTEXT.md` and `src/billing/CONTEXT.md`. The map says Ordering notifies Billing of cancellations. Preserve both routes and the unrelated map text.

Ordering currently contains:

```markdown
# Ordering

Human note: preserve the warehouse team's review annotations.

## Language

**Cancellation**:
The ending of an entire order before fulfillment.

**Order Line**:
A product and requested quantity belonging to one order.

## Relationships

- Each **Order Line** belongs to exactly one **Order**.

## Flagged Ambiguities

- Guest checkout ownership awaits review by Priya.
```

Billing contains an independently human-authored note: `Finance note: do not remove historical invoice terminology.` Its `Language` section defines **Cancellation** as reversing an invoice. The existing guest-checkout ambiguity and finance/warehouse notes are outside the cancellation agreement and must survive.

Relevant code excerpts, with paths supplied by repository navigation:

```text
src/ordering/cancel.ts:10-13
cancelOrder(order) {
  order.status = "cancelled";
  for (const line of order.lines) line.remainingQuantity = 0;
}

src/billing/adjust.ts:20-22
adjustForCancellation(invoice, amount) {
  return createCreditNote(invoice.id, amount);
}
```

These excerpts show a whole-order update and a credit-note operation. They do not prove which callers are reachable, whether a line-level alternative exists, or whether a runtime scenario succeeded. Inspect those additional sources if needed before extending the claim.

The user says: “Customers can cancel one unit of an unfulfilled three-unit line and still receive two. Support calls that cancellation, and finance also says cancellation.”

### Challenge, not silent correction

First surface the concrete conflict: Ordering's definition and shown method end the whole order, whereas the proposed scenario retains two requested units. Ask whether the requested domain rule is approved and the implementation is behind, or whether support means a different operation. Separately distinguish Billing's invoice reversal from a credit note and from a pre-invoice quantity reduction.

Probe the relationship before proposing its cardinality:

- Order O contains line L requesting three units and a second line M requesting one. One unit of L is cancelled. Does M remain requested, and does L keep its identity with two units remaining?
- Can L later lose another unit? May the accepted cancellation quantity exceed its remaining two units? What about cancelling zero units?
- Does cancelling an unbilled unit require any credit note? Can one line's cancellation span more than one invoice, or is invoicing restricted? If the latter is unknown, keep that relationship unresolved.

### Explicit answers in this example

Assume the domain owner now confirms: a **Line Cancellation** concerns exactly one line, reduces it by a positive quantity no greater than remaining requested quantity, and can recur; the line retains identity, M is unchanged, and zero or excess quantities are invalid. The whole-order method is stale for this scenario; no code repair is authorized. Billing confirms **Credit Note** means a reduction of an invoiced amount owed, not invoice erasure. No credit note is required before invoicing. Neither owner can yet confirm how split invoices map to cancellations.

Capture the Ordering agreement immediately, not at session end: add the one-sentence Line Cancellation definition and `_Avoid_: cancellation, refund` under Language, and the agreed one-line/zero-or-many/positive-quantity relationships. Narrowly replace the old Cancellation entry only after agreement that it is obsolete; otherwise retain its distinct whole-order meaning with a disambiguating name agreed by the owner. Keep the warehouse note, Order Line definition and guest-checkout ambiguity unchanged. Record the corrected usage and retain a domain question for any unagreed whole-order operation.

Then capture Billing's separately agreed Credit Note definition and the no-credit-note-before-invoicing boundary. Rename or replace Billing's old Cancellation entry only to the extent the owner agrees; do not infer that every invoice reversal is a Credit Note. Preserve the finance note. Record the split-invoice relationship as unresolved rather than inventing one cancellation = one credit note.

The map needs no edit merely because terms changed if its context routes and relationship remain accurate. The lookup note needs no rewrite. Put source locations and the stale-method disposition in the session handoff, not API implementation details in the definitions. Do not edit the source files.

### Completion artifact for this example

| Item | Accounted outcome |
| --- | --- |
| Ordering line-level meaning | Agreed Line Cancellation definition captured in Ordering; whole-order meaning explicitly distinguished or unresolved |
| Cardinality and quantity | One cancellation -> exactly one line; line -> zero or more cancellations; positive quantity bounded by remaining requested quantity; L keeps identity and M is unchanged |
| Billing meaning | Agreed Credit Note definition captured in Billing; distinct from invoice erasure and an unbilled cancellation |
| Cross-context cardinality | Split-invoice mapping unresolved; owner/evidence needed, no one-to-one assumption |
| Code contradiction | Shown whole-order method conflicts with the agreed partial-cancellation scenario; implementation follow-on identified, no code changed or runtime success claimed |
| Human context | Existing map/routes and finance/warehouse notes preserved; guest-checkout ambiguity unchanged |
| ADR | No candidate merely for agreeing vocabulary or identifying stale code; apply the separate gate if a real implementation choice is later made |

This result is useful even with a remaining ambiguity: every in-scope claim has an honest status and the approved subset is durably recorded. Merely adding headings or copying this vocabulary into an unrelated repository does not perform the collaboration.
