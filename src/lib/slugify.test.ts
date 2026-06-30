import { describe, it, expect } from "vitest";
import cases from "../../sidecar/tests/fixtures/slugify_cases.json";
import { slugify } from "./slugify";

describe("slugify", () => {
    it.each(cases)("$input → $expected", ({ input, expected }) => {
        expect(slugify(input)).toBe(expected);
    });
});
