// Generates src/api.generated.js from FastAPI's auto-generated OpenAPI spec.
// Usage: npm run gen:api            (reads http://127.0.0.1:8000/openapi.json)
//        node scripts/gen-api.mjs path/to/openapi.json
import { readFileSync, writeFileSync } from 'node:fs'

const src = process.argv[2]
const spec = src
  ? JSON.parse(readFileSync(src, 'utf8'))
  : await (await fetch(process.env.API_URL || 'http://127.0.0.1:8000/openapi.json')).json()

const ops = {}
for (const [path, methods] of Object.entries(spec.paths)) {
  for (const [method, op] of Object.entries(methods)) {
    if (!op.operationId) continue
    ops[op.operationId] = { method: method.toUpperCase(), path, summary: op.summary || '' }
  }
}
const out = `// AUTO-GENERATED from the FastAPI OpenAPI spec by scripts/gen-api.mjs - do not edit.\n` +
  `export const operations = ${JSON.stringify(ops, null, 2)}\n`
writeFileSync(new URL('../src/api.generated.js', import.meta.url), out)
console.log(`generated ${Object.keys(ops).length} operations`)
