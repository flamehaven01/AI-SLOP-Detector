// One bundle of the modules `npm test` exercises, so they share one copy of
// state.ts (the diagnostics the provider reads are the ones updateDiagnostics set).
export { initState } from '../src/state';
export { updateDiagnostics } from '../src/diagnostics';
export { SlopCodeActionProvider, extractModuleName, appendListEntry } from '../src/codeActions';
export { parseGateDecision, isInside } from '../src/backendText';
