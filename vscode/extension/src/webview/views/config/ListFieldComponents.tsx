import React from 'react';
import { Field } from './FieldComponents.js';

export interface StringListItem {
  id: string;
  value: string;
}

export interface KeyValueListItem {
  id: string;
  key: string;
  value: string;
}

interface EditableListFieldProps<TItem extends { id: string }> {
  items: TItem[];
  emptyText: string;
  addLabel: string;
  hint: React.ReactNode;
  onChange: (items: TItem[]) => void;
  createItem: () => TItem;
  renderItem: (item: TItem, index: number, updateItem: (nextItem: TItem) => void) => React.ReactNode;
}

export const EditableListField = <TItem extends { id: string }>({
  items,
  emptyText,
  addLabel,
  hint,
  onChange,
  createItem,
  renderItem,
}: EditableListFieldProps<TItem>) => {
  const updateItemAtIndex = (index: number, nextItem: TItem) => {
    const nextItems = [...items];
    nextItems[index] = nextItem;
    onChange(nextItems);
  };

  const removeItemAtIndex = (index: number) => {
    onChange(items.filter((_, itemIndex) => itemIndex !== index));
  };

  return (
    <div className="field">
      <div className="list-section">
        {items.length === 0 && <div className="list-section-empty">{emptyText}</div>}
        {items.map((item, index) => (
          <div key={item.id} className="list-row">
            {renderItem(item, index, (nextItem: TItem) => updateItemAtIndex(index, nextItem))}
            <vscode-button
              type="button"
              secondary
              onClick={() => removeItemAtIndex(index)}
            >
              ×
            </vscode-button>
          </div>
        ))}
        <div className="list-add-row">
          <vscode-button type="button" secondary onClick={() => onChange([...items, createItem()])}>
            {addLabel}
          </vscode-button>
        </div>
      </div>
      <div className="field-hint">{hint}</div>
    </div>
  );
};

interface EditableStringListFieldProps {
  items: StringListItem[];
  emptyText: string;
  addLabel: string;
  placeholder: (index: number) => string;
  hint: React.ReactNode;
  onChange: (items: StringListItem[]) => void;
  createItem: () => StringListItem;
}

export const EditableStringListField: React.FC<EditableStringListFieldProps> = ({
  items,
  emptyText,
  addLabel,
  placeholder,
  hint,
  onChange,
  createItem,
}) => (
  <EditableListField
    items={items}
    emptyText={emptyText}
    addLabel={addLabel}
    hint={hint}
    onChange={onChange}
    createItem={createItem}
    renderItem={(item, index, updateItem) => (
      <>
        <vscode-textfield
          value={item.value}
          placeholder={placeholder(index)}
          onInput={(event: any) => {
            updateItem({
              ...item,
              value: (event.target as HTMLInputElement).value,
            });
          }}
        />
      </>
    )}
  />
);

interface EditableKeyValueListFieldProps {
  items: KeyValueListItem[];
  emptyText: string;
  addLabel: string;
  keyPlaceholder: string;
  valuePlaceholder: string;
  hint: React.ReactNode;
  onChange: (items: KeyValueListItem[]) => void;
  createItem: () => KeyValueListItem;
}

export const EditableKeyValueListField: React.FC<EditableKeyValueListFieldProps> = ({
  items,
  emptyText,
  addLabel,
  keyPlaceholder,
  valuePlaceholder,
  hint,
  onChange,
  createItem,
}) => (
  <EditableListField
    items={items}
    emptyText={emptyText}
    addLabel={addLabel}
    hint={hint}
    onChange={onChange}
    createItem={createItem}
    renderItem={(item, _index, updateItem) => (
      <>
        <vscode-textfield
          className="list-row-key"
          style={{ flex: '0 0 36%' }}
          value={item.key}
          placeholder={keyPlaceholder}
          onInput={(event: any) => {
            updateItem({
              ...item,
              key: (event.target as HTMLInputElement).value,
            });
          }}
        />
        <vscode-textfield
          value={item.value}
          placeholder={valuePlaceholder}
          onInput={(event: any) => {
            updateItem({
              ...item,
              value: (event.target as HTMLInputElement).value,
            });
          }}
        />
      </>
    )}
  />
);
