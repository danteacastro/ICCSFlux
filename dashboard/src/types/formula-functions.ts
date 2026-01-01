// Formula Functions and Operators
// Available in all formula fields: calculate steps, wait conditions, ramp formulas, etc.
// User-defined constants/variables from playground are referenced as {VariableName}

// =============================================================================
// OPERATORS
// =============================================================================

export type ArithmeticOperator = '+' | '-' | '*' | '/' | '%' | '**'
export type ComparisonOperator = '==' | '!=' | '===' | '!==' | '>' | '<' | '>=' | '<='
export type LogicalOperator = '&&' | '||' | '!'
export type BitwiseOperator = '&' | '|' | '^' | '~' | '<<' | '>>' | '>>>'
export type AssignmentOperator = '=' | '+=' | '-=' | '*=' | '/='

export interface OperatorInfo {
  symbol: string
  name: string
  description: string
  example: string
  category: 'arithmetic' | 'comparison' | 'logical' | 'bitwise' | 'assignment'
  precedence: number  // Higher = evaluated first
}

export const OPERATORS: OperatorInfo[] = [
  // Arithmetic (highest precedence first)
  { symbol: '**', name: 'Exponentiation', description: 'Raise to power', example: '2 ** 3 = 8', category: 'arithmetic', precedence: 14 },
  { symbol: '*', name: 'Multiplication', description: 'Multiply two values', example: '3 * 4 = 12', category: 'arithmetic', precedence: 13 },
  { symbol: '/', name: 'Division', description: 'Divide two values', example: '10 / 2 = 5', category: 'arithmetic', precedence: 13 },
  { symbol: '%', name: 'Modulo', description: 'Remainder after division', example: '10 % 3 = 1', category: 'arithmetic', precedence: 13 },
  { symbol: '+', name: 'Addition', description: 'Add two values', example: '3 + 4 = 7', category: 'arithmetic', precedence: 12 },
  { symbol: '-', name: 'Subtraction', description: 'Subtract two values', example: '10 - 3 = 7', category: 'arithmetic', precedence: 12 },

  // Bitwise shift
  { symbol: '<<', name: 'Left Shift', description: 'Shift bits left', example: '1 << 2 = 4', category: 'bitwise', precedence: 11 },
  { symbol: '>>', name: 'Right Shift', description: 'Shift bits right (sign-preserving)', example: '8 >> 2 = 2', category: 'bitwise', precedence: 11 },
  { symbol: '>>>', name: 'Unsigned Right Shift', description: 'Shift bits right (zero-fill)', example: '-1 >>> 0 = 4294967295', category: 'bitwise', precedence: 11 },

  // Comparison
  { symbol: '<', name: 'Less Than', description: 'True if left < right', example: '3 < 5 = true', category: 'comparison', precedence: 10 },
  { symbol: '<=', name: 'Less Than or Equal', description: 'True if left <= right', example: '3 <= 3 = true', category: 'comparison', precedence: 10 },
  { symbol: '>', name: 'Greater Than', description: 'True if left > right', example: '5 > 3 = true', category: 'comparison', precedence: 10 },
  { symbol: '>=', name: 'Greater Than or Equal', description: 'True if left >= right', example: '5 >= 5 = true', category: 'comparison', precedence: 10 },
  { symbol: '==', name: 'Equal (loose)', description: 'True if values are equal (type coercion)', example: '5 == "5" = true', category: 'comparison', precedence: 9 },
  { symbol: '!=', name: 'Not Equal (loose)', description: 'True if values are not equal', example: '5 != 3 = true', category: 'comparison', precedence: 9 },
  { symbol: '===', name: 'Strict Equal', description: 'True if values and types are equal', example: '5 === 5 = true', category: 'comparison', precedence: 9 },
  { symbol: '!==', name: 'Strict Not Equal', description: 'True if values or types differ', example: '5 !== "5" = true', category: 'comparison', precedence: 9 },

  // Bitwise logical
  { symbol: '&', name: 'Bitwise AND', description: 'AND each bit', example: '5 & 3 = 1', category: 'bitwise', precedence: 8 },
  { symbol: '^', name: 'Bitwise XOR', description: 'XOR each bit', example: '5 ^ 3 = 6', category: 'bitwise', precedence: 7 },
  { symbol: '|', name: 'Bitwise OR', description: 'OR each bit', example: '5 | 3 = 7', category: 'bitwise', precedence: 6 },
  { symbol: '~', name: 'Bitwise NOT', description: 'Invert all bits', example: '~5 = -6', category: 'bitwise', precedence: 15 },

  // Logical
  { symbol: '!', name: 'Logical NOT', description: 'Invert boolean value', example: '!true = false', category: 'logical', precedence: 15 },
  { symbol: '&&', name: 'Logical AND', description: 'True if both operands are true', example: 'true && false = false', category: 'logical', precedence: 5 },
  { symbol: '||', name: 'Logical OR', description: 'True if either operand is true', example: 'true || false = true', category: 'logical', precedence: 4 },

  // Assignment (used in setVariable, calculate steps)
  { symbol: '=', name: 'Assignment', description: 'Assign value to variable', example: 'x = 5', category: 'assignment', precedence: 2 },
  { symbol: '+=', name: 'Add and Assign', description: 'Add and assign', example: 'x += 5 (x = x + 5)', category: 'assignment', precedence: 2 },
  { symbol: '-=', name: 'Subtract and Assign', description: 'Subtract and assign', example: 'x -= 5 (x = x - 5)', category: 'assignment', precedence: 2 },
  { symbol: '*=', name: 'Multiply and Assign', description: 'Multiply and assign', example: 'x *= 5 (x = x * 5)', category: 'assignment', precedence: 2 },
  { symbol: '/=', name: 'Divide and Assign', description: 'Divide and assign', example: 'x /= 5 (x = x / 5)', category: 'assignment', precedence: 2 },
]

// =============================================================================
// BUILT-IN MATH FUNCTIONS (LabVIEW-style)
// =============================================================================

export type FunctionCategory =
  | 'trigonometric'
  | 'hyperbolic'
  | 'exponential'
  | 'rounding'
  | 'comparison'
  | 'statistical'
  | 'conversion'
  | 'bitwise'
  | 'special'

export interface FunctionInfo {
  name: string
  signature: string
  description: string
  example: string
  category: FunctionCategory
  returns: string
}

export const MATH_FUNCTIONS: FunctionInfo[] = [
  // Trigonometric
  { name: 'sin', signature: 'sin(x)', description: 'Sine of angle in radians', example: 'sin(PI/2) = 1', category: 'trigonometric', returns: 'number' },
  { name: 'cos', signature: 'cos(x)', description: 'Cosine of angle in radians', example: 'cos(0) = 1', category: 'trigonometric', returns: 'number' },
  { name: 'tan', signature: 'tan(x)', description: 'Tangent of angle in radians', example: 'tan(PI/4) = 1', category: 'trigonometric', returns: 'number' },
  { name: 'asin', signature: 'asin(x)', description: 'Arcsine (inverse sine) in radians', example: 'asin(1) = PI/2', category: 'trigonometric', returns: 'number' },
  { name: 'acos', signature: 'acos(x)', description: 'Arccosine (inverse cosine) in radians', example: 'acos(1) = 0', category: 'trigonometric', returns: 'number' },
  { name: 'atan', signature: 'atan(x)', description: 'Arctangent (inverse tangent) in radians', example: 'atan(1) = PI/4', category: 'trigonometric', returns: 'number' },
  { name: 'atan2', signature: 'atan2(y, x)', description: 'Arctangent of y/x, handling quadrants', example: 'atan2(1, 1) = PI/4', category: 'trigonometric', returns: 'number' },

  // Hyperbolic
  { name: 'sinh', signature: 'sinh(x)', description: 'Hyperbolic sine', example: 'sinh(0) = 0', category: 'hyperbolic', returns: 'number' },
  { name: 'cosh', signature: 'cosh(x)', description: 'Hyperbolic cosine', example: 'cosh(0) = 1', category: 'hyperbolic', returns: 'number' },
  { name: 'tanh', signature: 'tanh(x)', description: 'Hyperbolic tangent', example: 'tanh(0) = 0', category: 'hyperbolic', returns: 'number' },
  { name: 'asinh', signature: 'asinh(x)', description: 'Inverse hyperbolic sine', example: 'asinh(0) = 0', category: 'hyperbolic', returns: 'number' },
  { name: 'acosh', signature: 'acosh(x)', description: 'Inverse hyperbolic cosine', example: 'acosh(1) = 0', category: 'hyperbolic', returns: 'number' },
  { name: 'atanh', signature: 'atanh(x)', description: 'Inverse hyperbolic tangent', example: 'atanh(0) = 0', category: 'hyperbolic', returns: 'number' },

  // Exponential & Logarithmic
  { name: 'exp', signature: 'exp(x)', description: 'e raised to power x', example: 'exp(1) = 2.718...', category: 'exponential', returns: 'number' },
  { name: 'log', signature: 'log(x)', description: 'Natural logarithm (base e)', example: 'log(E) = 1', category: 'exponential', returns: 'number' },
  { name: 'log10', signature: 'log10(x)', description: 'Base-10 logarithm', example: 'log10(100) = 2', category: 'exponential', returns: 'number' },
  { name: 'log2', signature: 'log2(x)', description: 'Base-2 logarithm', example: 'log2(8) = 3', category: 'exponential', returns: 'number' },
  { name: 'pow', signature: 'pow(base, exp)', description: 'Base raised to exponent', example: 'pow(2, 3) = 8', category: 'exponential', returns: 'number' },
  { name: 'sqrt', signature: 'sqrt(x)', description: 'Square root', example: 'sqrt(16) = 4', category: 'exponential', returns: 'number' },
  { name: 'cbrt', signature: 'cbrt(x)', description: 'Cube root', example: 'cbrt(27) = 3', category: 'exponential', returns: 'number' },
  { name: 'hypot', signature: 'hypot(a, b, ...)', description: 'Square root of sum of squares', example: 'hypot(3, 4) = 5', category: 'exponential', returns: 'number' },

  // Rounding
  { name: 'abs', signature: 'abs(x)', description: 'Absolute value', example: 'abs(-5) = 5', category: 'rounding', returns: 'number' },
  { name: 'ceil', signature: 'ceil(x)', description: 'Round up to nearest integer', example: 'ceil(4.2) = 5', category: 'rounding', returns: 'number' },
  { name: 'floor', signature: 'floor(x)', description: 'Round down to nearest integer', example: 'floor(4.8) = 4', category: 'rounding', returns: 'number' },
  { name: 'round', signature: 'round(x)', description: 'Round to nearest integer', example: 'round(4.5) = 5', category: 'rounding', returns: 'number' },
  { name: 'trunc', signature: 'trunc(x)', description: 'Remove fractional part', example: 'trunc(-4.8) = -4', category: 'rounding', returns: 'number' },
  { name: 'sign', signature: 'sign(x)', description: 'Sign of number (-1, 0, or 1)', example: 'sign(-5) = -1', category: 'rounding', returns: 'number' },
  { name: 'frac', signature: 'frac(x)', description: 'Fractional part only', example: 'frac(4.75) = 0.75', category: 'rounding', returns: 'number' },
  { name: 'roundTo', signature: 'roundTo(x, decimals)', description: 'Round to N decimal places', example: 'roundTo(3.14159, 2) = 3.14', category: 'rounding', returns: 'number' },

  // Comparison / Selection
  { name: 'min', signature: 'min(a, b, ...)', description: 'Minimum of values', example: 'min(3, 1, 4) = 1', category: 'comparison', returns: 'number' },
  { name: 'max', signature: 'max(a, b, ...)', description: 'Maximum of values', example: 'max(3, 1, 4) = 4', category: 'comparison', returns: 'number' },
  { name: 'clamp', signature: 'clamp(x, min, max)', description: 'Constrain value to range', example: 'clamp(15, 0, 10) = 10', category: 'comparison', returns: 'number' },
  { name: 'inRange', signature: 'inRange(x, min, max)', description: 'Check if value is in range', example: 'inRange(5, 0, 10) = true', category: 'comparison', returns: 'boolean' },
  { name: 'select', signature: 'select(cond, a, b)', description: 'Return a if cond is true, else b', example: 'select(true, 1, 2) = 1', category: 'comparison', returns: 'any' },

  // Statistical
  { name: 'avg', signature: 'avg(a, b, ...)', description: 'Average/mean of values', example: 'avg(2, 4, 6) = 4', category: 'statistical', returns: 'number' },
  { name: 'sum', signature: 'sum(a, b, ...)', description: 'Sum of values', example: 'sum(1, 2, 3) = 6', category: 'statistical', returns: 'number' },
  { name: 'random', signature: 'random()', description: 'Random number 0-1', example: 'random() = 0.xyz...', category: 'statistical', returns: 'number' },
  { name: 'randomInt', signature: 'randomInt(min, max)', description: 'Random integer in range', example: 'randomInt(1, 10)', category: 'statistical', returns: 'number' },

  // Conversion
  { name: 'degToRad', signature: 'degToRad(deg)', description: 'Convert degrees to radians', example: 'degToRad(180) = PI', category: 'conversion', returns: 'number' },
  { name: 'radToDeg', signature: 'radToDeg(rad)', description: 'Convert radians to degrees', example: 'radToDeg(PI) = 180', category: 'conversion', returns: 'number' },
  { name: 'celToFah', signature: 'celToFah(c)', description: 'Celsius to Fahrenheit', example: 'celToFah(100) = 212', category: 'conversion', returns: 'number' },
  { name: 'fahToCel', signature: 'fahToCel(f)', description: 'Fahrenheit to Celsius', example: 'fahToCel(32) = 0', category: 'conversion', returns: 'number' },
  { name: 'galToL', signature: 'galToL(gal)', description: 'Gallons to liters', example: 'galToL(1) = 3.785', category: 'conversion', returns: 'number' },
  { name: 'lToGal', signature: 'lToGal(l)', description: 'Liters to gallons', example: 'lToGal(3.785) = 1', category: 'conversion', returns: 'number' },
  { name: 'psiToBar', signature: 'psiToBar(psi)', description: 'PSI to bar', example: 'psiToBar(14.5) = 1', category: 'conversion', returns: 'number' },
  { name: 'barToPsi', signature: 'barToPsi(bar)', description: 'Bar to PSI', example: 'barToPsi(1) = 14.5', category: 'conversion', returns: 'number' },

  // Special / Engineering
  { name: 'lerp', signature: 'lerp(a, b, t)', description: 'Linear interpolation', example: 'lerp(0, 10, 0.5) = 5', category: 'special', returns: 'number' },
  { name: 'map', signature: 'map(x, inMin, inMax, outMin, outMax)', description: 'Map value from one range to another', example: 'map(5, 0, 10, 0, 100) = 50', category: 'special', returns: 'number' },
  { name: 'deadband', signature: 'deadband(x, center, width)', description: 'Apply deadband around center', example: 'deadband(1.5, 0, 2) = 0', category: 'special', returns: 'number' },
  { name: 'hysteresis', signature: 'hysteresis(x, low, high, prev)', description: 'Apply hysteresis switching', example: 'hysteresis(6, 5, 10, false) = false', category: 'special', returns: 'boolean' },
  { name: 'rateOfChange', signature: 'rateOfChange(current, previous, dt)', description: 'Calculate rate of change', example: 'rateOfChange(10, 5, 1) = 5', category: 'special', returns: 'number' },
  { name: 'movingAvg', signature: 'movingAvg(channelName, samples)', description: 'Moving average of channel', example: 'movingAvg("Temp1", 10)', category: 'special', returns: 'number' },
  { name: 'derivative', signature: 'derivative(channelName)', description: 'Rate of change of channel', example: 'derivative("Flow1")', category: 'special', returns: 'number' },
  { name: 'integral', signature: 'integral(channelName, reset?)', description: 'Running integral of channel', example: 'integral("Power")', category: 'special', returns: 'number' },
]

// =============================================================================
// BUILT-IN CONSTANTS
// =============================================================================

export interface ConstantInfo {
  name: string
  value: number
  description: string
}

export const BUILT_IN_CONSTANTS: ConstantInfo[] = [
  { name: 'PI', value: Math.PI, description: 'Pi (3.14159...)' },
  { name: 'E', value: Math.E, description: 'Euler\'s number (2.71828...)' },
  { name: 'LN2', value: Math.LN2, description: 'Natural log of 2' },
  { name: 'LN10', value: Math.LN10, description: 'Natural log of 10' },
  { name: 'LOG2E', value: Math.LOG2E, description: 'Base-2 log of E' },
  { name: 'LOG10E', value: Math.LOG10E, description: 'Base-10 log of E' },
  { name: 'SQRT2', value: Math.SQRT2, description: 'Square root of 2' },
  { name: 'SQRT1_2', value: Math.SQRT1_2, description: 'Square root of 1/2' },
  { name: 'INF', value: Infinity, description: 'Positive infinity' },
  { name: 'NAN', value: NaN, description: 'Not a Number' },
]

// =============================================================================
// CHANNEL REFERENCE SYNTAX
// =============================================================================

/**
 * In formulas, channels and variables can be referenced using:
 *
 * {ChannelName}     - Current value of channel
 * {ChannelName.avg} - Average value (if available)
 * {ChannelName.min} - Minimum value (if available)
 * {ChannelName.max} - Maximum value (if available)
 *
 * $VariableName     - User-defined variable from playground
 * @LoopVar          - Loop iterator variable (in forEach, etc.)
 * #ConstantName     - User-defined constant from playground
 *
 * Examples:
 *   {RTD_in} + {RTD_out} / 2           - Average of two RTDs
 *   {Flow_Total} >= $TargetVolume      - Compare to user constant
 *   sin(degToRad({Angle}))             - Trig on channel value
 *   clamp({Setpoint}, 0, 100)          - Constrain setpoint to range
 */

export type ChannelProperty = 'value' | 'avg' | 'min' | 'max' | 'rate' | 'raw'

export interface FormulaReference {
  type: 'channel' | 'variable' | 'constant' | 'loopVar'
  name: string
  property?: ChannelProperty
}

// Helper to parse formula references
export function parseFormulaReferences(formula: string): FormulaReference[] {
  const refs: FormulaReference[] = []

  // Match {ChannelName} or {ChannelName.property}
  const channelRegex = /\{([a-zA-Z_][a-zA-Z0-9_]*)(?:\.([a-zA-Z]+))?\}/g
  let match: RegExpExecArray | null
  while ((match = channelRegex.exec(formula)) !== null) {
    refs.push({
      type: 'channel',
      name: match[1]!,
      property: (match[2] as ChannelProperty) || 'value'
    })
  }

  // Match $VariableName
  const varRegex = /\$([a-zA-Z_][a-zA-Z0-9_]*)/g
  while ((match = varRegex.exec(formula)) !== null) {
    refs.push({ type: 'variable', name: match[1]! })
  }

  // Match #ConstantName
  const constRegex = /#([a-zA-Z_][a-zA-Z0-9_]*)/g
  while ((match = constRegex.exec(formula)) !== null) {
    refs.push({ type: 'constant', name: match[1]! })
  }

  // Match @LoopVar
  const loopRegex = /@([a-zA-Z_][a-zA-Z0-9_]*)/g
  while ((match = loopRegex.exec(formula)) !== null) {
    refs.push({ type: 'loopVar', name: match[1]! })
  }

  return refs
}

// Get all function names for autocomplete
export function getFunctionNames(): string[] {
  return MATH_FUNCTIONS.map(f => f.name)
}

// Get functions by category
export function getFunctionsByCategory(category: FunctionCategory): FunctionInfo[] {
  return MATH_FUNCTIONS.filter(f => f.category === category)
}

// Get operators by category
export function getOperatorsByCategory(category: OperatorInfo['category']): OperatorInfo[] {
  return OPERATORS.filter(o => o.category === category)
}
