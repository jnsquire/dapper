import { useState, useCallback } from 'react';
import { DebugConfiguration } from '../types/debug.js';

type FieldType<T> = T extends Array<any> ? string[] : T extends boolean ? boolean : string;

export function useFormState<T extends object>(initialState: T) {
  const [state, setState] = useState<T>(initialState);

  const updateField = useCallback(<K extends keyof T>(
    field: K,
    value: T[K] | ((prev: T[K]) => T[K])
  ) => {
    setState(prev => ({
      ...prev,
      [field]: typeof value === 'function' ? value(prev[field]) : value
    }));
  }, []);

  const handleChange = useCallback(<K extends keyof T>(
    field: K,
    value: FieldType<T[K]> | ((prev: FieldType<T[K]>) => FieldType<T[K]>)
  ) => {
    setState(prev => {
      const currentValue = prev[field];
      const newValue = typeof value === 'function' 
        ? (value as (prev: FieldType<T[K]>) => FieldType<T[K]>)(currentValue as FieldType<T[K]>) 
        : value;
      
      return {
        ...prev,
        [field]: newValue
      };
    });
  }, []);

  const handleEventChange = useCallback(<K extends keyof T>(
    field: K,
    event: Event & { target: { value?: string; checked?: boolean } }
  ) => {
    const target = event.target as HTMLInputElement;
    const value = target.type === 'checkbox' ? target.checked : target.value;
    
    setState(prev => ({
      ...prev,
      [field]: value
    }));
  }, []);

  return [state, { updateField, handleChange, handleEventChange, setState }] as const;
}
