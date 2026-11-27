/** What PackTherm answers and how far to trust it, for a first visit to the public site (v0.6.18). */
const REPO = "https://github.com/omlettehead22/PackTherm";

const FACTS: { value: string; what: string }[] = [
  { value: "0.65 K", what: "median error on 48 blind tests of a measured cell, from 25 to −20 °C" },
  { value: "5 cells", what: "checked against measured data, from LFP to NMC 811" },
  { value: "4 cells", what: "judged in every design: interior and wall, coolant inlet and outlet" },
];

export function Intro() {
  return (
    <section className="card intro" aria-labelledby="intro-title">
      <h1 id="intro-title">Design the cooling for a battery pack</h1>
      <p className="lede">
        Give PackTherm a cylindrical cell, a duty and your limits. It simulates air, cold plates, side ribbons,
        phase-change material and chillers in a packed module, and shows which designs pass, what they add in mass and
        what they cost to run.
      </p>
      <ul className="intro__facts">
        {FACTS.map((f) => (
          <li key={f.value}>
            <strong>{f.value}</strong>
            <span>{f.what}</span>
          </li>
        ))}
      </ul>
      <p className="muted">
        Start from an example below, or read <a href={`${REPO}#validation`}>how it is validated</a> and{" "}
        <a href={`${REPO}/blob/main/docs/BACKLOG.md`}>what it assumes</a>.
      </p>
    </section>
  );
}
