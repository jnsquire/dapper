import { useCallback } from 'react';

type InputElement = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
type EventHandler = (e: Event) => void;

/**
 * A simple hook to create event handlers for VS Code web components
 * @param onChange Callback when a field value changes
 * @returns Object with handler creators
 */
export function useWebComponentEvents<T extends object>(
  onChange: (field: keyof T, value: any) => void
) {
  // Create a generic change handler
  const createChangeHandler = useCallback(
    <K extends keyof T>(field: K) => 
      (e: Event) => {
        const target = e.target as (HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement);
        const value = target.type === 'checkbox' 
          ? (target as HTMLInputElement).checked 
          : target.value;
        
        onChange(field, value);
      },
    [onChange]
  );

  // Create an input handler (for text inputs)
  const createInputHandler = useCallback(
    <K extends keyof T>(field: K) => {
      const handler = createChangeHandler(field);
      return (e: Event) => {
        e.preventDefault();
        handler(e);
      };
    },
    [createChangeHandler]
  );

  // Create a checkbox handler
  const createCheckboxHandler = useCallback(
    <K extends keyof T>(field: K) => 
      (e: Event) => {
        e.preventDefault();
        const target = e.target as HTMLInputElement;
        onChange(field, target.checked);
      },
    [onChange]
  );

  // Create a select handler
  const createSelectHandler = useCallback(
    <K extends keyof T>(field: K) => 
      (e: Event) => {
        e.preventDefault();
        const target = e.target as HTMLSelectElement;
        onChange(field, target.value);
      },
    [onChange]
  );

  return {
    createInputHandler,
    createCheckboxHandler,
    createSelectHandler,
    createChangeHandler,
  };
}
