import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Intro } from "./components/Intro";

describe("Intro", () => {
  it("says what PackTherm answers and links to the validation and assumptions", () => {
    render(<Intro />);
    expect(screen.getByRole("heading", { level: 1, name: "Design the cooling for a battery pack" })).toBeTruthy();
    expect(screen.getByText("0.65 K")).toBeTruthy(); // the README's validation median
    expect(screen.getByRole("link", { name: "how it is validated" }).getAttribute("href")).toMatch(/#validation$/);
    expect(screen.getByRole("link", { name: "what it assumes" }).getAttribute("href")).toMatch(/BACKLOG\.md$/);
  });
});
