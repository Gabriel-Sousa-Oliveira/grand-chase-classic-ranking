import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("vercel-preview");
const output = resolve("vercel-dist");

if (!existsSync(source)) throw new Error("vercel-preview directory is missing");
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
cpSync(source, output, { recursive: true });
console.log("Vercel public preview generated in vercel-dist");
