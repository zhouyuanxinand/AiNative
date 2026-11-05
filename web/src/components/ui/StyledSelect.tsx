import { useId, useState, type ReactNode } from 'react';
import { Select } from 'antd';
import './antdControls.css';

export interface StyledSelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

export interface StyledSelectGroup {
  label: ReactNode;
  options: StyledSelectOption[];
}

interface StyledSelectProps {
  id?: string;
  name?: string;
  value: string;
  options: (StyledSelectOption | StyledSelectGroup)[];
  onChange: (value: string) => void;
  className?: string;
  placeholder?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  invalid?: boolean;
  autoFocus?: boolean;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
}

export function StyledSelect({
  id, name, value, options, onChange, className = '', placeholder = '请选择',
  disabled = false, required = false, invalid = false, autoFocus = false,
  'aria-label': ariaLabel, 'aria-labelledby': ariaLabelledby, 'aria-describedby': ariaDescribedby,
}: StyledSelectProps) {
  const generatedId = useId().replaceAll(':', '');
  const [open, setOpen] = useState(false);
  const flatOptions = options.flatMap(option => 'options' in option ? option.options : [option]);
  const accessibleOption = (option: StyledSelectOption) => ({ ...option, 'aria-disabled': option.disabled || undefined });
  const selectOptions = options.map(option => 'options' in option
    ? { ...option, options: option.options.map(accessibleOption) } : accessibleOption(option));
  // An empty option can be an intentional “all” filter. An absent empty value shows the placeholder.
  const selectedValue = value === '' && !flatOptions.some(option => option.value === '') ? undefined : value;
  return <div className={`select-control platform-select-control ${open && !disabled ? 'open' : ''} ${disabled ? 'disabled' : ''} ${invalid ? 'invalid-field' : ''} ${className}`.trim()}>
    <Select<string>
      id={id || `styled-select-${generatedId}`}
      className="platform-select"
      classNames={{ popup: { root: 'platform-select-popup' } }}
      value={selectedValue}
      options={selectOptions}
      onChange={onChange}
      onOpenChange={setOpen}
      disabled={disabled}
      autoFocus={autoFocus}
      placeholder={placeholder}
      status={invalid ? 'error' : undefined}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledby}
      aria-describedby={ariaDescribedby}
      aria-invalid={invalid}
      aria-required={required}
      virtual={false}
      listHeight={260}
      // Existing settings still use the browser's dialog top layer. Body portals would be behind it.
      getPopupContainer={trigger => trigger.closest('dialog') ?? trigger.closest('.ant-modal-content') ?? document.body}
    />
    {name && <input type="hidden" name={name} value={value} disabled={disabled} />}
  </div>;
}
