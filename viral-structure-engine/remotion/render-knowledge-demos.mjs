import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { bundle } from '@remotion/bundler';
import { openBrowser, renderMedia, selectComposition } from '@remotion/renderer';

const remotionDir = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const plan = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
  const outputDir = path.resolve(plan.output_dir);
  const expectedOutput = path.resolve(remotionDir, '../../web/backend/storage/knowledge_demos');
  if (outputDir !== expectedOutput) throw new Error('Unexpected demo output directory');
  const idPattern = plan.personal === true ? /^k_u\d+_[A-Za-z0-9_]+$/ : /^k_\d+$/;
  if (!Array.isArray(plan.entries) || plan.entries.some((entry) => !idPattern.test(entry.id))) {
    throw new Error('Invalid knowledge-demo entry ID');
  }
  const publicDir = plan.personal ? path.resolve(plan.asset_dir) : path.join(remotionDir, 'public');
  if (plan.personal && publicDir !== path.join(expectedOutput, 'footage_assets')) throw new Error('Unexpected footage asset directory');

  const localDir = path.resolve(remotionDir, '../../.local');
  await fs.mkdir(localDir, { recursive: true });
  const bundleDir = await fs.mkdtemp(path.join(localDir, 'knowledge-demo-bundle-'));
  let browser;
  let failed = 0;
  const started = Date.now();

  try {
    console.log(`Preparing shared teaching-demo bundle (${plan.entries.length} entries)`);
    const serveUrl = await bundle({ entryPoint: path.join(remotionDir, 'src/index.ts'), outDir: bundleDir, publicDir, enableCaching: true });
    browser = await openBrowser('chrome', { logLevel: 'error' });
    await fs.mkdir(outputDir, { recursive: true });
    for (const [index, entry] of plan.entries.entries()) {
      const output = path.join(outputDir, `${entry.id}${plan.personal ? '.teaching' : ''}.mp4`);
      const temporary = path.join(outputDir, `${entry.id}.${randomUUID()}.partial.mp4`);
      const began = Date.now();
      try {
        const inputProps = plan.personal ? entry.input_props : { kind: entry.kind, tech_id: entry.tech_id, title: entry.title };
        const composition = await selectComposition({ serveUrl, id: plan.personal ? 'PersonalKnowledgeDemo' : 'TechniqueDemo', inputProps, puppeteerInstance: browser, logLevel: 'error' });
        await renderMedia({ serveUrl, composition, inputProps, puppeteerInstance: browser, outputLocation: temporary, codec: 'h264', pixelFormat: 'yuv420p', imageFormat: 'jpeg', concurrency: 4, logLevel: 'error', overwrite: true });
        const stat = await fs.stat(temporary);
        if (!stat.size) throw new Error('Renderer produced an empty video');
        await fs.rename(temporary, output);
        if (plan.personal) await fs.writeFile(path.join(outputDir, `${entry.id}.teaching.json`), JSON.stringify({ status: 'ready', fingerprint: entry.fingerprint, mode: entry.mode, render_token: entry.render_token, materials: entry.materials, recipe: entry.input_props }));
        console.log(`[${index + 1}/${plan.entries.length}] OK ${entry.id} ${entry.title} ${Math.round(stat.size / 1024)}KB ${((Date.now() - began) / 1000).toFixed(1)}s`);
      } catch (error) {
        failed += 1;
        await fs.unlink(temporary).catch(() => {});
        console.error(`[${index + 1}/${plan.entries.length}] FAIL ${entry.id}: ${error.message}`);
      }
    }
    console.log(`Completed: ${plan.entries.length - failed} succeeded, ${failed} failed, ${((Date.now() - started) / 1000).toFixed(1)}s`);
    if (failed) process.exitCode = 1;
  } finally {
    if (browser) await browser.close({ silent: true });
    // This is the unique directory just created above, confined to project .local.
    const resolved = path.resolve(bundleDir);
    if (path.dirname(resolved) === localDir && path.basename(resolved).startsWith('knowledge-demo-bundle-')) {
      await fs.rm(resolved, { recursive: true, force: true });
    }
  }
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
