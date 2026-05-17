import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const generatedPath = 'src/api/schema.d.ts';
const tempDir = join(tmpdir(), 'garrison-openapi-types-check');
const tempPath = join(tempDir, 'schema.d.ts');

mkdirSync(tempDir, { recursive: true });

try {
  execFileSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', '../docs/openapi.json', '-o', tempPath],
    {
      stdio: 'inherit'
    }
  );

  if (!existsSync(generatedPath)) {
    console.error(`${generatedPath} does not exist. Run npm run api:types.`);
    process.exit(1);
  }

  const expected = readFileSync(tempPath, 'utf8');
  const current = readFileSync(generatedPath, 'utf8');

  if (expected !== current) {
    console.error(`${generatedPath} is stale. Run npm run api:types.`);
    process.exit(1);
  }
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
