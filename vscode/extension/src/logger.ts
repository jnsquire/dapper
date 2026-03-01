// previous standalone implementation moved into utils/logger to keep a single
// definitive logger class.  this file now re-exports the same symbols so
// other modules that were importing from the root path continue to work.

export { Logger, logger, registerLoggerCommands } from './utils/logger.js';
