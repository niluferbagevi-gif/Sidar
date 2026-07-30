import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

// Shared controlled-form state helper. Replaces the `setXForm((prev) => ({
// ...prev, [key]: value }))` updater that used to be duplicated per form
// (see OperationsQaPanel.jsx history) with one reusable field setter.
export type FormState = Record<string, unknown>;

export type FormStateResult<T extends FormState> = [
  T,
  <K extends keyof T>(key: K, value: T[K]) => void,
  Dispatch<SetStateAction<T>>,
];

export function useFormState<T extends FormState>(initialValues: T): FormStateResult<T> {
  const [values, setValues] = useState(initialValues);
  const setField = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);
  return [values, setField, setValues];
}
