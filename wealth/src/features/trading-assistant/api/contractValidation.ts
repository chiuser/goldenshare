import { contractSchemas, type Contracts } from "./generatedContracts";
import { validCombination } from "./contractSemantics";

type Schema = Record<string, unknown>;
const schemas = contractSchemas as Record<string, Schema>;

export class InvalidTradingAssistantResponse extends Error {
  constructor() { super("交易助手返回的数据不完整，请重新读取"); }
}

function fail(): never { throw new InvalidTradingAssistantResponse(); }
const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function validDate(value: string): boolean {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith("0000")) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function wireValue(value: string, schema: Schema) {
  const tag = schema["x-ta-value"];
  if (tag === "uuid" && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)) fail();
  if (tag === "version") {
    if (!/^(0|[1-9][0-9]*)$/.test(value)) fail();
    const integer = BigInt(value);
    if (integer < BigInt(schema["x-ta-min-integer"] as string) || integer > BigInt(schema["x-ta-max-integer"] as string)) fail();
  }
  if (tag === "date" && !validDate(value)) fail();
  if (tag === "month" && (!/^[0-9]{4}-[0-9]{2}$/.test(value) || !validDate(value + "-01"))) fail();
  if (tag === "instant" || tag === "deadline") {
    if (!/T.*(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value) || !Number.isFinite(Date.parse(value)) || !validDate(value.slice(0, 10))) fail();
    if (tag === "deadline" && !/T[0-9]{2}:[0-9]{2}(?::00)?\+08:00$/.test(value)) fail();
  }
  if (tag === "stock-code" && (!value || value !== value.trim().toUpperCase())) fail();
  if (tag === "money" || tag === "decimal-input") {
    // JS `$` may match before a final newline; monetary text must match in full.
    if (!/^-?[0-9]+(?:\.[0-9]{1,2})?$/.test(value) || /\s/.test(value)) fail();
    if (value === "-0.00") fail();
    const [whole, decimals = ""] = value.replace(/^-/, "").split(".");
    if (typeof schema["x-ta-integer-digits"] === "number" && (whole.replace(/^0+/, "") || "0").length > schema["x-ta-integer-digits"]) fail();
    const cents = BigInt(whole + decimals.padEnd(2, "0")) * (value.startsWith("-") ? -1n : 1n);
    if (typeof schema["x-ta-min-cents"] === "string" && cents < BigInt(schema["x-ta-min-cents"])) fail();
    if (typeof schema["x-ta-max-cents"] === "string" && cents > BigInt(schema["x-ta-max-cents"])) fail();
  }
  if (schema["x-ta-required-text"] === true && !value.trim()) fail();
  if (typeof schema["x-ta-max-graphemes"] === "number") {
    const segmenter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    if (Array.from(segmenter.segment(value)).length > schema["x-ta-max-graphemes"]) fail();
  }
}

function validate(value: unknown, schema: Schema): void {
  if (typeof schema.$ref === "string") {
    const target = schemas[schema.$ref.replace("#/$defs/", "")];
    if (!target) fail();
    validate(value, target); return;
  }
  const alternatives = schema.anyOf ?? schema.oneOf;
  if (Array.isArray(alternatives)) {
    let valid = 0;
    for (const alternative of alternatives) {
      try { validate(value, alternative as Schema); valid++; } catch (error) {
        if (!(error instanceof InvalidTradingAssistantResponse)) throw error;
      }
    }
    if (valid === 0 || (schema.oneOf && valid !== 1)) fail();
    return;
  }
  if ("const" in schema && value !== schema.const) fail();
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) fail();
  switch (schema.type) {
    case "object": {
      if (!object(value)) fail();
      const properties = schema.properties as Record<string, Schema>;
      for (const required of (schema.required ?? []) as string[]) if (!Object.hasOwn(value, required)) fail();
      for (const [key, entry] of Object.entries(value)) {
        if (!Object.hasOwn(properties, key)) fail();
        validate(entry, properties[key]);
      }
      if (!validCombination(schema.title, value)) fail();
      return;
    }
    case "array":
      if (!Array.isArray(value)) fail();
      if (typeof schema.minItems === "number" && value.length < schema.minItems) fail();
      if (typeof schema.maxItems === "number" && value.length > schema.maxItems) fail();
      for (const entry of value) validate(entry, schema.items as Schema);
      return;
    case "string":
      if (typeof value !== "string") fail();
      if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) fail();
      if (typeof schema.minLength === "number" && [...value].length < schema.minLength) fail();
      if (typeof schema.maxLength === "number" && [...value].length > schema.maxLength) fail();
      wireValue(value, schema); return;
    case "integer": case "number":
      if (typeof value !== "number" || !Number.isFinite(value) || (schema.type === "integer" && !Number.isSafeInteger(value))) fail();
      if (typeof schema.minimum === "number" && value < schema.minimum) fail();
      if (typeof schema.maximum === "number" && value > schema.maximum) fail();
      return;
    case "boolean": if (typeof value !== "boolean") fail(); return;
    case "null": if (value !== null) fail(); return;
    default: fail();
  }
}

export function parseContract<K extends keyof Contracts>(name: K, value: unknown): Contracts[K] {
  validate(value, schemas[name]);
  return value as Contracts[K];
}

export function validInputField(name: keyof Contracts, field: string, value: unknown): boolean {
  const property = (schemas[name].properties as Record<string, Schema> | undefined)?.[field];
  if (!property) throw new Error("Unknown generated input field");
  try { validate(value, property); return true; } catch (error) {
    if (error instanceof InvalidTradingAssistantResponse) return false;
    throw error;
  }
}
