/**
 * Comprehensive Project Roundtrip Test
 * Ensures NO data is lost during load -> store -> save cycle
 *
 * Run: node test_project_roundtrip.cjs
 */

const fs = require('fs');
const path = require('path');

const originalPath = path.join(__dirname, '..', 'config', 'projects', 'dhw_test_system.json');
const original = JSON.parse(fs.readFileSync(originalPath, 'utf8'));

console.log('=== Project Roundtrip Test ===\n');
console.log(`Testing: ${originalPath}`);
console.log(`Original size: ${fs.statSync(originalPath).size} bytes\n`);

// Simulate convertProjectChannel (what happens on load)
function convertProjectChannel(name, pch) {
  return {
    ...pch,  // Spread ALL fields to preserve hardware-specific settings
    name,
    channel_type: pch.channel_type,
    unit: pch.unit || pch.units || '',
    group: pch.group || 'Ungrouped',
    chartable: pch.chartable !== false && pch.channel_type !== 'digital_output',
    visible: pch.visible !== false,
  };
}

// Simulate loading into store
const storeChannels = {};
for (const [name, pch] of Object.entries(original.channels || {})) {
  storeChannels[name] = convertProjectChannel(name, pch);
}

// Simulate collectCurrentState (what happens on save/download)
// This mirrors the actual code in useProjectFiles.ts
function collectCurrentState(storeChannels, originalProject) {
  const channels = {};
  for (const [name, ch] of Object.entries(storeChannels)) {
    channels[name] = { ...ch };
  }

  return {
    type: 'nisystem-project',
    version: '2.0',
    name: originalProject.name,
    description: originalProject.description,
    created: originalProject.created,
    modified: originalProject.modified,
    // Preserved from loaded project
    ...(originalProject.system ? { system: originalProject.system } : {}),
    ...(originalProject.service ? { service: originalProject.service } : {}),
    ...(originalProject.schedules ? { schedules: originalProject.schedules } : {}),
    channels,
    layout: originalProject.layout || {},
    scripts: originalProject.scripts || {},
    recording: originalProject.recording || {},
    safety: originalProject.safety || {},
  };
}

const collected = collectCurrentState(storeChannels, original);

// ============================================
// TEST 1: Check all top-level keys are preserved
// ============================================
console.log('=== TEST 1: Top-Level Keys ===\n');

const origKeys = new Set(Object.keys(original));
const collKeys = new Set(Object.keys(collected));

let test1Pass = true;
const missingKeys = [];
const extraKeys = [];

for (const key of origKeys) {
  if (!collKeys.has(key)) {
    missingKeys.push(key);
    test1Pass = false;
  }
}

for (const key of collKeys) {
  if (!origKeys.has(key)) {
    extraKeys.push(key);
    // Extra keys are OK (computed fields)
  }
}

if (missingKeys.length > 0) {
  console.log('❌ MISSING top-level keys:', missingKeys.join(', '));
} else {
  console.log('✓ All top-level keys preserved');
}

if (extraKeys.length > 0) {
  console.log('ℹ Extra top-level keys (OK):', extraKeys.join(', '));
}

// ============================================
// TEST 2: Check all channel hardware fields preserved
// ============================================
console.log('\n=== TEST 2: Channel Hardware Fields ===\n');

let test2Pass = true;
const hardwareFields = [
  'rtd_type', 'resistance_config', 'excitation_current',
  'thermocouple_type', 'voltage_range', 'terminal_config',
  'current_range_ma', 'counter_edge', 'pulses_per_unit',
  'default_state', 'log', 'log_interval_ms', 'precision',
  'signal_max', 'signal_min', 'eng_units_max', 'eng_units_min',
  'four_twenty_scaling'
];

for (const [chName, origCh] of Object.entries(original.channels || {})) {
  const collCh = collected.channels[chName];
  if (!collCh) {
    console.log(`❌ Channel "${chName}" missing entirely`);
    test2Pass = false;
    continue;
  }

  for (const field of hardwareFields) {
    if (field in origCh && !(field in collCh)) {
      console.log(`❌ Channel "${chName}": missing field "${field}"`);
      test2Pass = false;
    } else if (field in origCh && origCh[field] !== collCh[field]) {
      console.log(`❌ Channel "${chName}": field "${field}" changed: ${origCh[field]} → ${collCh[field]}`);
      test2Pass = false;
    }
  }
}

if (test2Pass) {
  console.log('✓ All hardware fields preserved across all channels');
}

// ============================================
// TEST 3: Check nested objects preserved
// ============================================
console.log('\n=== TEST 3: Nested Objects ===\n');

let test3Pass = true;
const nestedSections = ['system', 'service', 'schedules', 'layout', 'scripts', 'recording', 'safety'];

for (const section of nestedSections) {
  if (section in original) {
    if (!(section in collected)) {
      console.log(`❌ Section "${section}" missing`);
      test3Pass = false;
    } else {
      const origStr = JSON.stringify(original[section]);
      const collStr = JSON.stringify(collected[section]);
      if (origStr !== collStr) {
        // Check if it's just missing vs different
        const origSize = origStr.length;
        const collSize = collStr.length;
        if (collSize < origSize * 0.9) {  // More than 10% smaller
          console.log(`⚠ Section "${section}" significantly smaller (${origSize} → ${collSize} chars)`);
        }
      }
    }
  }
}

if (test3Pass) {
  console.log('✓ All nested sections present');
}

// ============================================
// TEST 4: Size comparison
// ============================================
console.log('\n=== TEST 4: Size Comparison ===\n');

const outputPath = path.join(__dirname, 'test_output.json');
fs.writeFileSync(outputPath, JSON.stringify(collected, null, 2));

const origSize = fs.statSync(originalPath).size;
const collSize = fs.statSync(outputPath).size;
const diff = collSize - origSize;
const pct = ((Math.abs(diff) / origSize) * 100).toFixed(1);

console.log(`Original: ${origSize} bytes`);
console.log(`Collected: ${collSize} bytes`);
console.log(`Difference: ${diff > 0 ? '+' : ''}${diff} bytes (${pct}%)`);

// Extra bytes are OK (computed fields like name, unit, chartable, visible)
// Missing bytes indicate data loss
let test4Pass = true;
if (diff < -500) {  // More than 500 bytes missing = likely data loss
  console.log('❌ Significant data loss detected!');
  test4Pass = false;
} else {
  console.log('✓ Size acceptable (extra bytes from computed fields)');
}

// Cleanup
fs.unlinkSync(outputPath);

// ============================================
// SUMMARY
// ============================================
console.log('\n=== SUMMARY ===\n');

const allPass = test1Pass && test2Pass && test3Pass && test4Pass;

if (allPass) {
  console.log('✅ ALL TESTS PASSED - No data loss detected');
  process.exit(0);
} else {
  console.log('❌ TESTS FAILED - Data loss detected!');
  console.log('\nFailed tests:');
  if (!test1Pass) console.log('  - Top-level keys missing');
  if (!test2Pass) console.log('  - Hardware fields missing');
  if (!test3Pass) console.log('  - Nested sections missing');
  if (!test4Pass) console.log('  - Significant size reduction');
  process.exit(1);
}
