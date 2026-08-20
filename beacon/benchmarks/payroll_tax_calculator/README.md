# Progressive Payroll & Income Tax Calculation Benchmark

## Domain & System Overview
This benchmark models statutory progressive income tax brackets, FICA social insurance contributions, dependent credits, and healthcare allowances commonly implemented in government, human resources, and enterprise payroll systems.

## Business Logic & Invariant Specifications
1. **Exempt Category Rule**: Employees marked with tax bracket `EXEMPT` incur $\$0.0$ federal and state income tax liabilities.
2. **Deductions Rule**: Taxable income is calculated by subtracting statutory retirement contributions and dependent allowances ($\$2,000$ per dependent) from gross salary.
3. **Progressive Marginal Brackets**:
   - $10\%$ on taxable income up to $\$20,000$.
   - $20\%$ on taxable income between $\$20,000$ and $\$80,000$.
   - $30\%$ on taxable income exceeding $\$80,000$.
4. **State Surcharge**: A $5\%$ state tax applies to taxable income over $\$30,000$ for non-exempt employees.
5. **Healthcare Tax Credit**: Eligible employees earning under $\$50,000$ with active health coverage receive up to $\$500$ tax credit reduction against federal tax.
6. **Social Security / Medicare (FICA)**: $6.2\%$ Social Security tax (capped at $\$140,000$ base) plus $1.45\%$ uncapped Medicare tax.

## Provenance
- **Category**: `PUBLIC`
- **License**: MIT
- **Legacy Version**: `1.0.0`
- **Modernized Version**: `2.0.0`
- **Controlled Buggy Variants**:
  - `buggy_bracket_v2`: Top tax bracket threshold altered from $\$80,000$ to $\$120,000$.
  - `buggy_deduction_v2`: Dependent allowance mutated from $\$2,000$ to $\$500$.
