import { useEffect, useState } from 'react';
import {
  type KeyValueListItem,
  type StringListItem,
} from '../components/ConfigViewComponents.js';
import { DebugConfiguration } from '../types/debug.js';

const generateId = () => Math.random().toString(36).substr(2, 9);

type ConfigUpdater = (updates: Partial<DebugConfiguration>) => void;

interface ListBinding<Item> {
  items: Item[];
  updateItems: (newItems: Item[]) => void;
}

interface ListCodec<Model, Item> {
  toItems: (model: Model) => Item[];
  toModel: (items: Item[]) => Model;
  matches: (items: Item[], model: Model) => boolean;
}

function useMirroredListBinding<Model, Item>(
  model: Model,
  updateModel: (model: Model) => void,
  codec: ListCodec<Model, Item>,
): ListBinding<Item> {
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    if (!codec.matches(items, model)) {
      setItems(codec.toItems(model));
    }
  }, [codec, items, model]);

  const updateItems = (newItems: Item[]) => {
    setItems(newItems);
    updateModel(codec.toModel(newItems));
  };

  return { items, updateItems };
}

function createStringListCodec(options?: { dropEmpty?: boolean }): ListCodec<string[], StringListItem> {
  const dropEmpty = options?.dropEmpty ?? false;

  return {
    toItems: (values) => values.map((value) => ({ id: generateId(), value })),
    toModel: (items) => items.map((item) => item.value).filter((value) => !dropEmpty || Boolean(value)),
    matches: (items, values) => {
      const committedValues = items.map((item) => item.value).filter((value) => !dropEmpty || Boolean(value));
      return JSON.stringify(values) === JSON.stringify(committedValues);
    },
  };
}

const envListCodec: ListCodec<Record<string, string>, KeyValueListItem> = {
  toItems: (env) => Object.entries(env).map(([key, value]) => ({ id: generateId(), key, value })),
  toModel: (items) => items.reduce((acc, curr) => {
    if (curr.key) {
      acc[curr.key] = curr.value;
    }
    return acc;
  }, {} as Record<string, string>),
  matches: (items, env) => {
    const committedEnv = items
      .filter((entry) => entry.key.trim())
      .reduce((acc, curr) => ({ ...acc, [curr.key]: curr.value }), {} as Record<string, string>);

    const envKeys = Object.keys(env).sort();
    const committedKeys = Object.keys(committedEnv).sort();
    const keysMatch = JSON.stringify(envKeys) === JSON.stringify(committedKeys);
    return keysMatch && envKeys.every((key) => env[key] === committedEnv[key]);
  },
};

interface UseRuntimeListsResult {
  argsList: StringListItem[];
  envList: KeyValueListItem[];
  modulePathsList: StringListItem[];
  updateArgs: (newList: StringListItem[]) => void;
  updateEnv: (newList: KeyValueListItem[]) => void;
  updateModulePaths: (newList: StringListItem[]) => void;
  createStringListItem: (value?: string) => StringListItem;
  createKeyValueListItem: (key?: string, value?: string) => KeyValueListItem;
}

/**
 * The runtime step edits arrays and key/value maps through list widgets that need
 * stable row ids for React rendering and focus management. The canonical config
 * shape does not have those ids, so this hook keeps a UI-facing mirror of the
 * runtime fields and translates changes back into the plain DebugConfiguration.
 *
 * `config` remains the source of truth. The local lists only exist so the editor
 * can preserve blank/in-progress rows without constantly regenerating item ids.
 */
export function useRuntimeLists(
  config: DebugConfiguration,
  updateConfig: ConfigUpdater,
): UseRuntimeListsResult {
  const stringArgsCodec = createStringListCodec();
  const modulePathCodec = createStringListCodec({ dropEmpty: true });

  // Rebuild the UI lists only when the underlying config changed externally.
  // That lets the widgets keep stable row ids while the user edits in place.
  const argsBinding = useMirroredListBinding(
    config.args || [],
    (args) => updateConfig({ args }),
    stringArgsCodec,
  );

  // Environment variables use a different codec because blank rows are valid
  // UI state but are not committed into the config object until a key exists.
  const envBinding = useMirroredListBinding(
    config.env || {},
    (env) => updateConfig({ env }),
    envListCodec,
  );

  // Module search paths intentionally drop empty rows when writing back so the
  // config only contains committed paths, not transient placeholders.
  const modulePathsBinding = useMirroredListBinding(
    config.moduleSearchPaths || [],
    (moduleSearchPaths) => updateConfig({ moduleSearchPaths }),
    modulePathCodec,
  );

  const createStringListItem = (value = ''): StringListItem => ({ id: generateId(), value });
  const createKeyValueListItem = (key = '', value = ''): KeyValueListItem => ({ id: generateId(), key, value });

  return {
    argsList: argsBinding.items,
    envList: envBinding.items,
    modulePathsList: modulePathsBinding.items,
    updateArgs: argsBinding.updateItems,
    updateEnv: envBinding.updateItems,
    updateModulePaths: modulePathsBinding.updateItems,
    createStringListItem,
    createKeyValueListItem,
  };
}