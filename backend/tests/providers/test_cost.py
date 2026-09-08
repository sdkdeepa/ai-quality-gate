from app.providers.cost import GEMINI_PRICING, OPENAI_PRICING, TableCostCalculator


class TestTableCostCalculator:
    def test_estimates_cost_from_pricing_table(self):
        calculator = TableCostCalculator({"model-a": (1.0, 2.0)})

        cost = calculator.estimate("model-a", input_tokens=1_000_000, output_tokens=500_000)

        assert cost == 1.0 + 1.0

    def test_zero_tokens_yields_zero_cost(self):
        calculator = TableCostCalculator({"model-a": (1.0, 2.0)})

        assert calculator.estimate("model-a", input_tokens=0, output_tokens=0) == 0.0

    def test_unknown_model_falls_back_to_default_price(self):
        calculator = TableCostCalculator({"model-a": (1.0, 2.0)})

        cost = calculator.estimate("unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)

        assert cost == 0.0

    def test_custom_default_price_applies_to_unknown_models(self):
        calculator = TableCostCalculator({}, default_price=(0.5, 0.5))

        cost = calculator.estimate("unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)

        assert cost == 1.0

    def test_result_is_rounded(self):
        calculator = TableCostCalculator({"model-a": (0.15, 0.60)})

        cost = calculator.estimate("model-a", input_tokens=37, output_tokens=11)

        assert cost == round((37 / 1_000_000) * 0.15 + (11 / 1_000_000) * 0.60, 8)


class TestPricingTables:
    def test_openai_pricing_has_known_default_model(self):
        assert "gpt-4o-mini" in OPENAI_PRICING

    def test_gemini_pricing_has_known_default_model(self):
        assert "gemini-2.5-flash" in GEMINI_PRICING
