import assert from "node:assert/strict";
import { test } from "node:test";
import type { I18nLocalized, I18nUnit } from "../../api/types";
import { fillTemplate, filterUnits, initialLanguage, message, needsAttention, pickText, unitKey } from "./translationUtils";

const unit = (over: Partial<I18nUnit>): I18nUnit => ({
  entity_type: "QUESTION", entity_key: "age", field: "label", label: "Question age", context: "", multiline: false,
  max_len: 100, source: "How old are you?", value: "Shekara nawa kake?", status: "AI_DRAFT", issues: [], ...over,
});

const units = [
  unit({}),
  unit({ entity_key: "b", status: "MISSING", value: null }),
  unit({ entity_key: "c", status: "OUTDATED" }),
  unit({ entity_key: "d", status: "EDITED", issues: [{ severity: "WARN", code: "UNCHANGED", message: "x" }] }),
  unit({ entity_key: "e", status: "REVIEWED" }),
];

test("filters pick the right units", () => {
  const keys = (f: Parameters<typeof filterUnits>[1]) => filterUnits(units, f).map((u) => u.entity_key);
  assert.deepEqual(keys("all"), ["age", "b", "c", "d", "e"]);
  assert.deepEqual(keys("missing"), ["b"]);
  assert.deepEqual(keys("outdated"), ["c"]);
  assert.deepEqual(keys("issues"), ["d"]);
  assert.deepEqual(keys("attention"), ["b", "c", "d"]);
  assert.deepEqual(keys("unreviewed"), ["age", "d"]);
});

test("search looks in the source, the translation and the label", () => {
  assert.equal(filterUnits(units, "all", "shekara").length, 4); // the missing one has no translation text
  assert.equal(filterUnits(units, "all", "HOW OLD").length, 5);
  assert.equal(filterUnits(units, "all", "nothing like this").length, 0);
});

test("placeholders are filled and unknown ones are left alone", () => {
  assert.equal(fillTemplate("Must be at least {min}.", { min: 18 }), "Must be at least 18.");
  assert.equal(fillTemplate("{answered} of {total}", { answered: 3 }), "3 of {total}");
});

test("standard messages come from the language or fall back to English", () => {
  const loc = { messages: { "msg.min": "Dole ne ya zama akalla {min}." } } as unknown as I18nLocalized;
  assert.equal(message(loc, "msg.min", "Must be at least {min}.", { min: 18 }), "Dole ne ya zama akalla 18.");
  assert.equal(message(loc, "msg.max", "Must be at most {max}.", { max: 5 }), "Must be at most 5.");
  assert.equal(message(null, "msg.max", "Must be at most {max}.", { max: 5 }), "Must be at most 5.");
});

test("text falls back to the original field by field", () => {
  assert.equal(pickText("Shekara?", "Age?"), "Shekara?");
  assert.equal(pickText(undefined, "Age?"), "Age?");
  assert.equal(pickText("   ", "Age?"), "Age?");
  assert.equal(pickText(undefined, null), null);
});

test("the remembered language is used only while it is still offered", () => {
  assert.equal(initialLanguage("ha", ["ha", "fr"]), "ha");
  assert.equal(initialLanguage("yo", ["ha", "fr"]), "");
  assert.equal(initialLanguage(null, ["ha"]), "");
});

test("keys and attention flag", () => {
  assert.equal(unitKey(units[0]), "QUESTION|age|label");
  assert.equal(needsAttention({ missing: 0, outdated: 0, blocked: 0 }), false);
  assert.equal(needsAttention({ missing: 0, outdated: 1, blocked: 0 }), true);
});
