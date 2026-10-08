import fs from 'node:fs';
import path from 'node:path';

const [sourcePath, outputPath, commit] = process.argv.slice(2);
if (!sourcePath || !outputPath || !commit) {
  throw new Error('usage: node json-to-junit.mjs <jest-json> <junit-xml> <commit>');
}

const result = JSON.parse(fs.readFileSync(sourcePath, 'utf8'));
const escape = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&apos;');

let tests = 0;
let failures = 0;
let skipped = 0;
let durationMs = 0;
const suites = (result.testResults ?? []).map((fileResult) => {
  const assertions = fileResult.assertionResults ?? [];
  let suiteFailures = 0;
  let suiteSkipped = 0;
  let suiteDurationMs = 0;
  const cases = assertions.map((assertion) => {
    const status = assertion.status;
    const duration = Number(assertion.duration ?? 0);
    tests += 1;
    durationMs += duration;
    suiteDurationMs += duration;
    const attributes = `classname="${escape(fileResult.name)}" name="${escape(assertion.fullName || assertion.title)}" time="${(duration / 1000).toFixed(3)}"`;
    if (status === 'pending' || status === 'todo' || status === 'skipped') {
      skipped += 1;
      suiteSkipped += 1;
      return `    <testcase ${attributes}><skipped/></testcase>`;
    }
    if (status !== 'passed') {
      failures += 1;
      suiteFailures += 1;
      const message = (assertion.failureMessages ?? []).join('\n');
      return `    <testcase ${attributes}><failure message="${escape(message)}">${escape(message)}</failure></testcase>`;
    }
    return `    <testcase ${attributes}/>`;
  });
  return [
    `  <testsuite name="${escape(path.relative(process.cwd(), fileResult.name))}" tests="${assertions.length}" failures="${suiteFailures}" skipped="${suiteSkipped}" errors="0" time="${(suiteDurationMs / 1000).toFixed(3)}">`,
    ...cases,
    '  </testsuite>',
  ].join('\n');
});

const xml = [
  '<?xml version="1.0" encoding="UTF-8"?>',
  `<testsuites tests="${tests}" failures="${failures}" skipped="${skipped}" errors="0" time="${(durationMs / 1000).toFixed(3)}">`,
  '  <properties>',
  `    <property name="source_json" value="${escape(sourcePath)}"/>`,
  `    <property name="commit" value="${escape(commit)}"/>`,
  '    <property name="converter" value="json-to-junit.mjs: assertion-result preserving"/>',
  '  </properties>',
  ...suites,
  '</testsuites>',
  '',
].join('\n');
fs.writeFileSync(outputPath, xml);
