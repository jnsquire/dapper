module.exports = {
  preset: 'ts-jest/presets/default-esm',
  testEnvironment: 'node',
  transformIgnorePatterns: ["/node_modules/"],
  moduleNameMapper: {
    '^vscode$': '<rootDir>/test/__mocks__/vscode.mjs'
  },
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', { useESM: true, diagnostics: { ignoreCodes: [151002] } }]
  },
  extensionsToTreatAsEsm: ['.ts']
  ,
  testMatch: ["<rootDir>/test/**/*.test.(js|ts)"]
  ,
  modulePathIgnorePatterns: ["<rootDir>/out/"]
};
