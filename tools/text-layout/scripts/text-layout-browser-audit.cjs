const { DEFAULT_VIEWPORTS, discoverIndexPages, resolveTemplateAssets } = require('./text-layout-browser-discovery.cjs');
const { createAuditExpression, createStressExpression } = require('./text-layout-browser-probes.cjs');
const { CDPClient, getJson, resolveEdgePath, waitForPage, waitForTarget } = require('./text-layout-browser-engine.cjs');
const { runBrowserAudit } = require('./text-layout-browser-runner.cjs');

async function main(args = process.argv.slice(2), auditOptions = {}) {
  const rootIndex = args.indexOf('--root');
  const root = rootIndex >= 0 && args[rootIndex + 1] ? args[rootIndex + 1] : process.cwd();
  const report = await runBrowserAudit(root, { progress: true, allPages: true, ...(args.includes('--project') ? {scopes:['.']} : {}), ...auditOptions });
  console.log(`Auditoría visual de texto: ${report.pagesScanned} páginas, ${report.viewportsChecked} vistas, ${report.findings.length} hallazgos.`);
  if (report.findings.length) {
    const findingsByRule = {};
    const findingsByProject = {};
    for (const finding of report.findings) {
      findingsByRule[finding.rule] = (findingsByRule[finding.rule] || 0) + 1;
      const project = finding.page.split('/').slice(0, 2).join('/');
      findingsByProject[project] = (findingsByProject[project] || 0) + 1;
    }
    console.log(`Hallazgos por regla: ${JSON.stringify(findingsByRule)}`);
    console.log(`Ámbitos con hallazgos: ${JSON.stringify(findingsByProject)}`);
  }
  if (args.includes('--json')) console.log(JSON.stringify(report, null, 2));
  for (const finding of report.findings.slice(0, 30)) {
    console.log(`${finding.page} [${finding.viewport}] ${finding.rule}: ${finding.detail} (${finding.selector})`);
  }
  return report.findings.length ? 1 : 0;
}

function setProcessExitCode(code) {
  process.exitCode = code;
}

function reportCliError(error) {
  console.error(error.message);
  process.exitCode = 1;
}

async function runFromCommandLine(args = process.argv.slice(2), auditOptions = {}) {
  try {
    setProcessExitCode(await main(args, auditOptions));
  } catch (error) {
    reportCliError(error);
  }
}

module.exports = {
  DEFAULT_VIEWPORTS,
  createAuditExpression,
  createStressExpression,
  CDPClient,
  discoverIndexPages,
  getJson,
  main,
  reportCliError,
  resolveTemplateAssets,
  resolveEdgePath,
  runFromCommandLine,
  runBrowserAudit,
  setProcessExitCode,
  waitForPage,
  waitForTarget
};

if (require.main === module) {
  runFromCommandLine();
}
