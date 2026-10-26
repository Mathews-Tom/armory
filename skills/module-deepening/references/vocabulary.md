# Vocabulary

Load before either mode. Use these terms exactly in questions, report cards and recommendations. Consistent language is the point: substitutes such as "component", "service", "API" or "boundary" each mean something slightly different and make findings harder to compare.

Domain nouns come from the project's `CONTEXT.md` / `CONTEXT-MAP.md`; architecture nouns come from this file. "The Order intake module is shallow" uses both correctly.

## Glossary

**Module**: anything with an interface and an implementation. Deliberately scale-agnostic: a function, class, package or a slice spanning tiers. _Avoid_: unit, component, service.

**Interface**: everything a caller must know to use the module correctly: the type signature, plus invariants, ordering constraints, error modes, required configuration and performance characteristics. _Avoid_: API, signature (too narrow; they cover only the type-level surface).

**Implementation**: what is inside a module, its body of code. Distinct from **adapter**: a thing can be a small adapter with a large implementation (a Postgres repository) or a large adapter with a small implementation (an in-memory fake). Say "adapter" when the seam is the topic, "implementation" otherwise.

**Depth**: leverage at the interface; the amount of behaviour a caller (or test) can exercise per unit of interface it has to learn. A module is **deep** when a large amount of behaviour sits behind a small interface, and **shallow** when the interface is nearly as complex as the implementation.

**Seam** (Michael Feathers): a place where behaviour can be altered without editing in that place; the *location* where a module's interface lives. Where to put the seam is its own design decision, separate from what goes behind it. _Avoid_: boundary (overloaded with DDD's bounded context).

**Adapter**: a concrete thing that satisfies an interface at a seam. Describes *role* (which slot it fills), not substance (what is inside).

**Leverage**: what callers get from depth. More capability per unit of interface learned; one implementation pays back across N call sites and M tests.

**Locality**: what maintainers get from depth. Change, bugs, knowledge and verification concentrate in one place instead of spreading across callers. Fix once, fixed everywhere.

## Deep versus shallow

```text
Deep module                         Shallow module (avoid)
┌─────────────────────┐             ┌─────────────────────────────────┐
│   Small interface   │ few entry   │       Large interface           │ many entry
├─────────────────────┤ points      ├─────────────────────────────────┤ points
│                     │             │  Thin implementation            │ passes
│ Deep implementation │ complexity  └─────────────────────────────────┘ through
│                     │ hidden
└─────────────────────┘
```

When shaping an interface, ask: can the number of entry points shrink? Can the parameters get simpler? Can more complexity move inside?

## Principles

- **Depth is a property of the interface, not the implementation.** A deep module may be built from small, swappable parts internally; they are just not part of its interface.
- **The deletion test.** Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep. A candidate for deepening is one where merging or deleting *concentrates* complexity rather than merely moving it.
- **The interface is the test surface.** Callers and tests cross the same seam. Wanting to test *past* the interface signals the module is the wrong shape.
- **One adapter means a hypothetical seam; two adapters mean a real one.** Do not introduce a seam unless something actually varies across it (typically production and test).
- **Internal seams versus external seams.** A deep module can have internal seams, private to its implementation and used by its own tests, as well as the external seam at its interface. Do not expose internal seams through the interface just because tests use them.

## Relationships

- A **module** has exactly one **interface**: the surface it presents to callers and tests.
- **Depth** is a property of a **module**, measured against its **interface**.
- A **seam** is where a **module**'s **interface** lives.
- An **adapter** sits at a **seam** and satisfies the **interface**.
- **Depth** produces **leverage** for callers and **locality** for maintainers.

## Rejected framings

- **Depth as the ratio of implementation lines to interface lines** (Ousterhout): rewards padding the implementation. Depth here means leverage.
- **"Interface" as the TypeScript `interface` keyword or a class's public methods**: too narrow. The interface includes every fact a caller must know.
- **"Boundary"**: overloaded with DDD's bounded context. Say **seam** or **interface**.
- **"Cleaner" or "easier to maintain"** as a benefit: not in this glossary and not checkable. Name the gain as leverage, locality or a smaller interface.

## Designing for testability

Good interfaces make tests natural:

1. **Accept dependencies, don't create them.**

   ```typescript
   // Testable: the gateway arrives at the seam
   function processOrder(order: Order, paymentGateway: PaymentGateway) {}

   // Hard to test: the dependency is created inside
   function processOrder(order: Order) {
     const gateway = new StripeGateway();
   }
   ```

2. **Return results, don't produce side effects.**

   ```typescript
   // Testable
   function calculateDiscount(cart: Cart): Discount {}

   // Hard to test
   function applyDiscount(cart: Cart): void {
     cart.total -= discount;
   }
   ```

3. **Small surface area.** Fewer entry points mean fewer tests; fewer parameters mean simpler setup.
