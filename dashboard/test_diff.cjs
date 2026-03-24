const fs = require('fs');
const path = require('path');

const originalPath = path.join(__dirname, '..', 'config', 'projects', 'dhw_test_system.json');
const original = JSON.parse(fs.readFileSync(originalPath, 'utf8'));

// Simulate the roundtrip
function convertProjectChannel(name, pch) {
  return {
    ...pch,
    name,
    channel_type: pch.channel_type,
    unit: pch.unit || pch.units || '',
    group: pch.group || 'Ungrouped',
    chartable: pch.chartable !== false && pch.channel_type !== 'digital_output',
    visible: pch.visible !== false,
  };
}

const storeChannels = {};
for (const [name, pch] of Object.entries(original.channels || {})) {
  storeChannels[name] = convertProjectChannel(name, pch);
}

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
    modified: originalProject.modified, // Keep same for comparison
    ...(originalProject.system ? { system: originalProject.system } : {}),
    ...(originalProject.service ? { service: originalProject.service } : {}),
    channels,
    layout: originalProject.layout || {},
    scripts: originalProject.scripts || {},
    recording: originalProject.recording || {},
    safety: originalProject.safety || {},
  };
}

const collected = collectCurrentState(storeChannels, original);

// Find differences
console.log('=== Missing Top-Level Keys in Collected ===');
for (const key of Object.keys(original)) {
  if (!(key in collected)) {
    console.log(`  MISSING: ${key}`);
  }
}

console.log('\n=== Extra Top-Level Keys in Collected ===');
for (const key of Object.keys(collected)) {
  if (!(key in original)) {
    console.log(`  EXTRA: ${key}`);
  }
}

console.log('\n=== Channel Field Differences ===');
const sampleChannel = 'RTD_in';
const origCh = original.channels[sampleChannel];
const collCh = collected.channels[sampleChannel];

console.log(`\nOriginal "${sampleChannel}" keys:`, Object.keys(origCh).sort().join(', '));
console.log(`\nCollected "${sampleChannel}" keys:`, Object.keys(collCh).sort().join(', '));

const origKeys = new Set(Object.keys(origCh));
const collKeys = new Set(Object.keys(collCh));

console.log('\nKeys in collected but not original:');
for (const k of collKeys) {
  if (!origKeys.has(k)) console.log(`  + ${k}: ${JSON.stringify(collCh[k])}`);
}

console.log('\nKeys in original but not collected:');
for (const k of origKeys) {
  if (!collKeys.has(k)) console.log(`  - ${k}: ${JSON.stringify(origCh[k])}`);
}

// Check schedules section (was in original)
console.log('\n=== Schedules Section ===');
console.log('Original has schedules:', 'schedules' in original);
console.log('Collected has schedules:', 'schedules' in collected);
