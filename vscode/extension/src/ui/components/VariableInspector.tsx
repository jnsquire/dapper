import * as React from 'react';

interface Variable {
  name: string;
  type: string;
  value: string;
  variablesReference: number;
  children?: Variable[];
}

interface VariableInspectorProps {
  variables: Variable[];
}

export const VariableInspector: React.FC<VariableInspectorProps> = ({
  variables = []
}) => {
  const [expandedVars, setExpandedVars] = React.useState<Set<number>>(new Set());

  const toggleExpand = (reference: number) => {
    const newExpanded = new Set(expandedVars);
    if (expandedVars.has(reference)) {
      newExpanded.delete(reference);
    } else {
      newExpanded.add(reference);
    }
    setExpandedVars(newExpanded);
  };

  const renderVariable = (variable: Variable, depth = 0) => {
    const hasChildren = variable.variablesReference > 0;
    const isExpanded = expandedVars.has(variable.variablesReference);

    return (
      <div key={`${variable.name}-${depth}`} className="variable-item" style={{ marginLeft: `${depth * 16}px` }}>
        <div 
          className="variable-header" 
          onClick={() => hasChildren && toggleExpand(variable.variablesReference)}
          style={{ cursor: hasChildren ? 'pointer' : 'default' }}
        >
          {hasChildren && (
            <span className="toggle-icon">
              {isExpanded ? '▼' : '►'}
            </span>
          )}
          <span className="variable-name">{variable.name}: </span>
          <span className="variable-type">{variable.type}</span>
          <span className="variable-value">{variable.value}</span>
        </div>
        {hasChildren && isExpanded && (
          <div className="variable-children">
            {variable.children?.map(child => renderVariable(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="variable-inspector">
      <div className="variable-inspector-header">
        <h2>Variables</h2>
      </div>
      <div className="variable-list">
        {variables.length > 0 ? (
          variables.map(variable => renderVariable(variable))
        ) : (
          <div className="no-variables">No variables in scope</div>
        )}
      </div>
    </div>
  );
};
