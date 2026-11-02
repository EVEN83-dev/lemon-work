from .models import SkillResult, SkillDef

METADATA = {
    "name": "finance_assistant",
    "version": "2.0.0",
    "category": "finance",
    "description": "Financial analysis with real computation: loan/mortgage, compound interest, ROI, depreciation.",
}


def execute(
    query: str = "",
    analysis_type: str = "trend",
    principal: float = 0,
    rate: float = 0,
    periods: int = 0,
    payment: float = 0,
    **kwargs,
) -> SkillResult:
    if not query and principal <= 0:
        return SkillResult.fail("query or principal+rate+periods is required")

    valid_types = ("trend", "comparison", "forecast", "loan", "compound", "roi", "depreciation")
    if analysis_type not in valid_types:
        return SkillResult.fail(
            "Invalid analysis_type '" + str(analysis_type) + "'. Must be one of: " + str(valid_types)
        )

    try:
        if analysis_type == "loan":
            return _calc_loan(query, principal, rate, periods, payment)
        elif analysis_type == "compound":
            return _calc_compound(query, principal, rate, periods)
        elif analysis_type == "roi":
            return _calc_roi(query, principal, payment)
        elif analysis_type == "depreciation":
            return _calc_depreciation(query, principal, periods)
        else:
            return _calc_general(query, analysis_type, principal, rate, periods)
    except Exception as e:
        return SkillResult.fail("Finance calculation error: " + str(e))


def _calc_loan(query: str, principal: float, rate: float, periods: int, payment: float) -> SkillResult:
    if principal <= 0 or rate <= 0 or periods <= 0:
        return SkillResult.fail("Loan calculation requires principal>0, rate>0, periods>0")

    monthly_rate = rate / 100 / 12
    if monthly_rate == 0:
        monthly_payment = principal / periods
    else:
        monthly_payment = principal * (monthly_rate * (1 + monthly_rate) ** periods) / ((1 + monthly_rate) ** periods - 1)

    total_paid = monthly_payment * periods
    total_interest = total_paid - principal

    schedule = []
    balance = principal
    for month in range(1, min(periods + 1, 13)):
        interest = balance * monthly_rate
        principal_paid = monthly_payment - interest
        balance -= principal_paid
        schedule.append({
            "month": month,
            "payment": round(monthly_payment, 2),
            "principal": round(principal_paid, 2),
            "interest": round(interest, 2),
            "balance": round(max(0, balance), 2),
        })

    output = (
        "=== Loan Calculation ===\n"
        "Principal: " + str(round(principal, 2)) + "\n"
        "Annual Rate: " + str(round(rate, 4)) + "%\n"
        "Term: " + str(periods) + " months\n"
        "Monthly Payment: " + str(round(monthly_payment, 2)) + "\n"
        "Total Paid: " + str(round(total_paid, 2)) + "\n"
        "Total Interest: " + str(round(total_interest, 2)) + "\n"
        "Interest Ratio: " + str(round(total_interest / principal * 100, 2)) + "%\n\n"
        "Amortization Schedule (first 12 months):\n"
    )
    for s in schedule:
        output += (
            "  Month " + str(s["month"]) + ": Payment=" + str(s["payment"])
            + " Principal=" + str(s["principal"]) + " Interest=" + str(s["interest"])
            + " Balance=" + str(s["balance"]) + "\n"
        )

    return SkillResult.ok(
        output=output,
        data={
            "monthly_payment": round(monthly_payment, 2),
            "total_paid": round(total_paid, 2),
            "total_interest": round(total_interest, 2),
            "schedule": schedule,
        },
    )


def _calc_compound(query: str, principal: float, rate: float, periods: int) -> SkillResult:
    if principal <= 0 or rate <= 0 or periods <= 0:
        return SkillResult.fail("Compound interest requires principal>0, rate>0, periods>0")

    final_value = principal * (1 + rate / 100) ** periods
    total_interest = final_value - principal

    yearly_schedule = []
    balance = principal
    for year in range(1, min(periods + 1, 21)):
        interest = balance * rate / 100
        balance += interest
        yearly_schedule.append({
            "year": year,
            "interest": round(interest, 2),
            "balance": round(balance, 2),
        })

    output = (
        "=== Compound Interest ===\n"
        "Principal: " + str(round(principal, 2)) + "\n"
        "Annual Rate: " + str(round(rate, 4)) + "%\n"
        "Periods: " + str(periods) + " years\n"
        "Final Value: " + str(round(final_value, 2)) + "\n"
        "Total Interest: " + str(round(total_interest, 2)) + "\n"
        "Growth Multiple: " + str(round(final_value / principal, 4)) + "x\n\n"
        "Yearly Growth:\n"
    )
    for s in yearly_schedule:
        output += "  Year " + str(s["year"]) + ": Interest=" + str(s["interest"]) + " Balance=" + str(s["balance"]) + "\n"

    return SkillResult.ok(
        output=output,
        data={
            "final_value": round(final_value, 2),
            "total_interest": round(total_interest, 2),
            "growth_multiple": round(final_value / principal, 4),
            "schedule": yearly_schedule,
        },
    )


def _calc_roi(query: str, investment: float, returns: float) -> SkillResult:
    if investment <= 0:
        return SkillResult.fail("ROI requires investment>0")

    roi = (returns - investment) / investment * 100
    profit = returns - investment

    output = (
        "=== ROI Analysis ===\n"
        "Investment: " + str(round(investment, 2)) + "\n"
        "Returns: " + str(round(returns, 2)) + "\n"
        "Profit/Loss: " + str(round(profit, 2)) + "\n"
        "ROI: " + str(round(roi, 2)) + "%\n"
    )
    if roi > 0:
        output += "Assessment: Profitable investment\n"
    elif roi < 0:
        output += "Assessment: Loss-generating investment\n"
    else:
        output += "Assessment: Break-even\n"

    return SkillResult.ok(
        output=output,
        data={"roi": round(roi, 2), "profit": round(profit, 2), "investment": investment, "returns": returns},
    )


def _calc_depreciation(query: str, cost: float, useful_life: int) -> SkillResult:
    if cost <= 0 or useful_life <= 0:
        return SkillResult.fail("Depreciation requires cost>0, useful_life>0")

    salvage_value = cost * 0.1
    annual_dep = (cost - salvage_value) / useful_life

    schedule = []
    book_value = cost
    for year in range(1, useful_life + 1):
        book_value -= annual_dep
        schedule.append({
            "year": year,
            "depreciation": round(annual_dep, 2),
            "book_value": round(max(book_value, salvage_value), 2),
        })

    output = (
        "=== Straight-Line Depreciation ===\n"
        "Cost: " + str(round(cost, 2)) + "\n"
        "Salvage Value: " + str(round(salvage_value, 2)) + "\n"
        "Useful Life: " + str(useful_life) + " years\n"
        "Annual Depreciation: " + str(round(annual_dep, 2)) + "\n\n"
        "Schedule:\n"
    )
    for s in schedule:
        output += "  Year " + str(s["year"]) + ": Dep=" + str(s["depreciation"]) + " Book=" + str(s["book_value"]) + "\n"

    return SkillResult.ok(
        output=output,
        data={"annual_depreciation": round(annual_dep, 2), "salvage": round(salvage_value, 2), "schedule": schedule},
    )


def _calc_general(query: str, analysis_type: str, principal: float, rate: float, periods: int) -> SkillResult:
    import re as _re

    numbers = [float(x) for x in _re.findall(r'-?\d+\.?\d*', query)]
    output = "=== Financial Analysis ===\nQuery: " + query + "\nType: " + analysis_type + "\n\n"

    if len(numbers) >= 2:
        values = numbers
        mean_val = sum(values) / len(values)
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val

        if len(values) > 1:
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_dev = variance ** 0.5
        else:
            std_dev = 0

        growth_rates = []
        for i in range(1, len(values)):
            if values[i - 1] != 0:
                growth_rates.append((values[i] - values[i - 1]) / abs(values[i - 1]) * 100)

        output += (
            "Data Points: " + str(len(values)) + "\n"
            "Mean: " + str(round(mean_val, 4)) + "\n"
            "Min: " + str(round(min_val, 4)) + "\n"
            "Max: " + str(round(max_val, 4)) + "\n"
            "Range: " + str(round(range_val, 4)) + "\n"
            "Std Dev: " + str(round(std_dev, 4)) + "\n"
        )
        if growth_rates:
            avg_growth = sum(growth_rates) / len(growth_rates)
            output += "Avg Growth Rate: " + str(round(avg_growth, 2)) + "%\n"
    else:
        output += "Insufficient numeric data in query for calculation.\n"
        output += "Provide numbers in your query for automatic trend/forecast analysis.\n"

    return SkillResult.ok(output=output, data={"query": query, "analysis_type": analysis_type})


def register(registry) -> None:
    registry.register(SkillDef(
        name="finance_assistant",
        description="Financial analysis with real computation: loan amortization, compound interest, ROI, depreciation, trend analysis from numeric data.",
        category="finance",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Financial analysis question or numeric data",
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["trend", "comparison", "forecast", "loan", "compound", "roi", "depreciation"],
                    "description": "Type of financial analysis",
                },
                "principal": {
                    "type": "number",
                    "description": "Principal amount (for loan/compound/roi)",
                },
                "rate": {
                    "type": "number",
                    "description": "Annual interest rate in percent (e.g. 5.5 for 5.5%)",
                },
                "periods": {
                    "type": "integer",
                    "description": "Number of periods (months for loan, years for compound)",
                },
                "payment": {
                    "type": "number",
                    "description": "Payment or return amount (for ROI)",
                },
            },
            "required": [],
        },
        handler=execute,
        timeout=30,
    ))
