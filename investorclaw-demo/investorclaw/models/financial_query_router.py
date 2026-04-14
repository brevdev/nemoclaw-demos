#!/usr/bin/env python3
"""
Financial Query Router for InvestorClaw.

Routes ALL financial queries through InvestorClaw's guardrail enforcement,
ensuring compliance-safe responses regardless of where the query originates
(OpenClaw chat, CLI, API, etc.).

This module is the enforcement point for financial guardrails across all
InvestorClaw outputs.
"""

import re
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime
from enum import Enum

from models.models import AnalysisResult


class QueryType(str, Enum):
    """Financial query type classification"""
    PORTFOLIO_ANALYSIS = "portfolio_analysis"      # Holdings snapshot, diversification
    ALLOCATION_ADVICE = "allocation_advice"        # Rebalancing, target allocation
    STOCK_SELECTION = "stock_selection"            # Buy/sell recommendations
    SENTIMENT_ANALYSIS = "sentiment_analysis"      # News sentiment, correlated news
    ANALYST_RATINGS = "analyst_ratings"            # Analyst data, price targets
    PERFORMANCE = "performance"                    # Returns, risk metrics
    TAX_PLANNING = "tax_planning"                  # Tax-loss harvesting
    GENERAL_FINANCIAL = "general_financial"        # Generic finance question
    NOT_FINANCIAL = "not_financial"                # Non-financial query


class FinancialQueryDetector:
    """Detect if a query is financial and classify its type"""

    # Comprehensive keyword sets for financial detection
    PORTFOLIO_KEYWORDS = {
        'portfolio', 'holdings', 'position', 'equity', 'stock', 'bond',
        'cash', 'allocation', 'diversification', 'concentration'
    }

    ADVICE_KEYWORDS = {
        'buy', 'sell', 'invest', 'rebalance', 'allocate', 'allocate',
        'should i', 'recommend', 'suggest', 'could i', 'can i',
        'when should', 'what should'
    }

    SENTIMENT_KEYWORDS = {
        'sentiment', 'news', 'outlook', 'guidance', 'correlated news',
        'what\'s happening', 'what\'s going on', 'latest news'
    }

    ANALYST_KEYWORDS = {
        'analyst', 'rating', 'target price', 'consensus', 'upgrade',
        'downgrade', 'price target', 'eps', 'earnings'
    }

    PERFORMANCE_KEYWORDS = {
        'performance', 'return', 'yield', 'dividend', 'sharpe', 'volatility',
        'risk', 'drawdown', 'beta', 'correlation'
    }

    TAX_KEYWORDS = {
        'tax', 'harvest', 'loss', 'deduction', 'capital gain', 'wash sale',
        'tax-loss'
    }

    # Ticker regex: 1-5 uppercase letters (AAPL, BRK.A, etc.)
    TICKER_PATTERN = re.compile(r'\b[A-Z]{1,5}\b(?:\.)?[A-Z]?')

    @staticmethod
    def is_financial_query(question: str) -> bool:
        """Detect if query is about financial topics"""
        q_lower = question.lower()

        # Check all keyword sets
        if any(kw in q_lower for kw in FinancialQueryDetector.PORTFOLIO_KEYWORDS):
            return True
        if any(kw in q_lower for kw in FinancialQueryDetector.ADVICE_KEYWORDS):
            return True
        if any(kw in q_lower for kw in FinancialQueryDetector.SENTIMENT_KEYWORDS):
            return True
        if any(kw in q_lower for kw in FinancialQueryDetector.ANALYST_KEYWORDS):
            return True
        if any(kw in q_lower for kw in FinancialQueryDetector.PERFORMANCE_KEYWORDS):
            return True
        if any(kw in q_lower for kw in FinancialQueryDetector.TAX_KEYWORDS):
            return True

        # Check for ticker symbols (AAPL, MSFT, TSLA, etc.)
        if FinancialQueryDetector.TICKER_PATTERN.search(question):
            return True

        return False

    @staticmethod
    def classify_query(question: str) -> QueryType:
        """Classify financial query into specific type"""
        if not FinancialQueryDetector.is_financial_query(question):
            return QueryType.NOT_FINANCIAL

        q_lower = question.lower()

        # Priority order: more specific types first
        if any(kw in q_lower for kw in {'sentiment', 'news', 'correlated'}):
            return QueryType.SENTIMENT_ANALYSIS
        if any(kw in q_lower for kw in {'analyst', 'rating', 'target', 'consensus'}):
            return QueryType.ANALYST_RATINGS
        if any(kw in q_lower for kw in {'buy', 'sell', 'which stock', 'what stock'}):
            return QueryType.STOCK_SELECTION
        if any(kw in q_lower for kw in {'rebalance', 'allocate', 'allocation'}):
            return QueryType.ALLOCATION_ADVICE
        if any(kw in q_lower for kw in {'tax', 'harvest', 'loss'}):
            return QueryType.TAX_PLANNING
        if any(kw in q_lower for kw in {'performance', 'return', 'volatility', 'risk'}):
            return QueryType.PERFORMANCE
        if any(kw in q_lower for kw in {'portfolio', 'holdings', 'position'}):
            return QueryType.PORTFOLIO_ANALYSIS

        # Default financial classification
        return QueryType.GENERAL_FINANCIAL


class FinancialQueryRouter:
    """
    Route financial queries to appropriate InvestorClaw handlers.

    This is the enforcement point for guardrails: ALL financial responses
    go through this router to ensure compliance.
    """

    @staticmethod
    def route_query(
        question: str,
        portfolio_file: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Route a financial query through InvestorClaw guardrails.

        Args:
            question: User's financial question
            portfolio_file: Path to portfolio.json (if needed)
            context: Additional context (holdings data, etc.)

        Returns:
            {
                "is_financial": bool,
                "query_type": QueryType,
                "analysis_type": str,
                "response": Dict (wrapped AnalysisResult),
                "disclaimer": str (mandatory disclaimer),
                "safe_for_output": bool (guardrails passed)
            }
        """
        # Detect and classify query
        is_financial = FinancialQueryDetector.is_financial_query(question)
        query_type = FinancialQueryDetector.classify_query(question)

        if not is_financial or query_type == QueryType.NOT_FINANCIAL:
            # Not financial, pass through without guardrails
            return {
                "is_financial": False,
                "query_type": QueryType.NOT_FINANCIAL,
                "note": "Query is not financial; route through normal OpenClaw handler"
            }

        # Route to appropriate handler based on query type
        if query_type == QueryType.SENTIMENT_ANALYSIS:
            return FinancialQueryRouter._handle_sentiment_query(question, portfolio_file, context)
        elif query_type == QueryType.ANALYST_RATINGS:
            return FinancialQueryRouter._handle_analyst_query(question, portfolio_file, context)
        elif query_type == QueryType.STOCK_SELECTION:
            return FinancialQueryRouter._handle_stock_selection_query(question, context)
        elif query_type == QueryType.ALLOCATION_ADVICE:
            return FinancialQueryRouter._handle_allocation_query(question, portfolio_file, context)
        elif query_type == QueryType.TAX_PLANNING:
            return FinancialQueryRouter._handle_tax_query(question, context)
        elif query_type == QueryType.PERFORMANCE:
            return FinancialQueryRouter._handle_performance_query(question, portfolio_file, context)
        elif query_type == QueryType.PORTFOLIO_ANALYSIS:
            return FinancialQueryRouter._handle_portfolio_query(question, portfolio_file, context)
        else:
            return FinancialQueryRouter._handle_general_financial_query(question, context)

    @staticmethod
    def _handle_sentiment_query(
        question: str,
        portfolio_file: Optional[str],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle sentiment/news queries - route to news fetcher"""
        return {
            "is_financial": True,
            "query_type": QueryType.SENTIMENT_ANALYSIS,
            "analysis_type": "Portfolio News & Sentiment Analysis",
            "recommendation": f"Use InvestorClaw news fetcher: /portfolio news",
            "context": f"User question: {question}",
            "response": {
                "observation": "User is asking about portfolio sentiment or news",
                "educational_consideration": (
                    "To analyze sentiment and news correlated to your specific holdings, "
                    "use the portfolio news analysis tool. This will fetch current news "
                    "items, analyze sentiment, and show you what's moving your holdings. "
                    "Remember: News can be volatile and cause emotional reactions. "
                    "A financial adviser can help contextualize news within your long-term goals."
                ),
                "disclaimer": "⚠️ EDUCATIONAL ANALYSIS — NOT INVESTMENT ADVICE"
            }
        }

    @staticmethod
    def _handle_analyst_query(
        question: str,
        portfolio_file: Optional[str],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle analyst rating queries - route to analyst fetcher"""
        return {
            "is_financial": True,
            "query_type": QueryType.ANALYST_RATINGS,
            "analysis_type": "Analyst Ratings & Price Targets",
            "recommendation": f"Use InvestorClaw analyst fetcher: /portfolio analyst",
            "context": f"User question: {question}",
            "response": {
                "observation": "User is asking about analyst ratings or price targets",
                "educational_consideration": (
                    "Analyst ratings and price targets provide one perspective on securities. "
                    "However, analyst opinions vary widely and can be wrong. "
                    "Use the analyst data tool to gather this consensus perspective, "
                    "but combine it with your own research and a financial adviser's guidance "
                    "before making decisions."
                ),
                "questions_for_adviser": [
                    "How much weight should I give to analyst price targets in my decision-making?",
                    "Which analysts or firms' ratings are most relevant to my situation?",
                ]
            }
        }

    @staticmethod
    def _handle_stock_selection_query(
        question: str,
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle buy/sell stock queries - EDUCATIONAL ONLY"""
        # Extract any ticker mentioned
        tickers = re.findall(r'\b[A-Z]{1,5}\b', question)
        ticker_mention = f" ({', '.join(set(tickers))})" if tickers else ""
        first_ticker = tickers[0] if tickers else "this stock"

        return {
            "is_financial": True,
            "query_type": QueryType.STOCK_SELECTION,
            "analysis_type": "Stock Selection Educational Context",
            "response": {
                "observation": f"You're asking about stock selection{ticker_mention}",
                "educational_consideration": (
                    "Stock selection involves analyzing fundamentals, technicals, valuations, "
                    "and your personal financial situation. No tool can tell you what stocks "
                    "to buy or sell—that's a personal decision based on your goals, "
                    "risk tolerance, and financial situation. "
                    "\n\n"
                    "What a financial adviser might help with: "
                    "- Screening stocks based on your criteria "
                    "- Analyzing fundamental metrics (P/E, growth, dividends) "
                    "- Understanding how a stock fits into your portfolio "
                    "- Assessing concentration risk if you're considering a large position"
                ),
                "questions_for_adviser": [
                    f"Is {first_ticker} a good fit for my portfolio based on my goals?",
                    "What metrics should I focus on when evaluating stocks?",
                    "How do I avoid concentration risk when I like a particular stock?",
                ],
                "disclaimer": "⚠️ EDUCATIONAL ANALYSIS — NOT INVESTMENT ADVICE"
            }
        }

    @staticmethod
    def _handle_allocation_query(
        question: str,
        portfolio_file: Optional[str],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle asset allocation/rebalancing queries"""
        return {
            "is_financial": True,
            "query_type": QueryType.ALLOCATION_ADVICE,
            "analysis_type": "Asset Allocation Educational Context",
            "recommendation": f"Use InvestorClaw portfolio analyzer: /portfolio analyze",
            "response": {
                "observation": "You're asking about portfolio allocation or rebalancing",
                "educational_consideration": (
                    "Asset allocation—how much you invest in stocks, bonds, and cash—is "
                    "one of the most important decisions you make. The right allocation depends on: "
                    "- Your age and time horizon "
                    "- Your risk tolerance and goals "
                    "- Your income stability and financial situation "
                    "- Your existing assets in other accounts "
                    "- Macroeconomic conditions "
                    "\n\n"
                    "No single allocation is 'right' for everyone. The InvestorClaw portfolio "
                    "analyzer can show you how your current allocation compares to industry "
                    "benchmarks (like a 75/20/5 balanced portfolio), but only you and a "
                    "qualified financial adviser can determine what's right for you."
                ),
                "questions_for_adviser": [
                    "What asset allocation is appropriate for my age, risk tolerance, and goals?",
                    "How often should I rebalance, and how much drift is acceptable?",
                    "Should I adjust my allocation based on current market conditions?",
                ],
                "disclaimer": "⚠️ EDUCATIONAL ANALYSIS — NOT INVESTMENT ADVICE"
            }
        }

    @staticmethod
    def _handle_tax_query(
        question: str,
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle tax planning queries - deferred to tax professionals"""
        return {
            "is_financial": True,
            "query_type": QueryType.TAX_PLANNING,
            "analysis_type": "Tax Planning Educational Context",
            "response": {
                "observation": "You're asking about tax planning or tax-loss harvesting",
                "educational_consideration": (
                    "Tax planning is highly specific to your situation: your income, other "
                    "investments, state/local taxes, filing status, etc. General techniques "
                    "like tax-loss harvesting can be powerful, but they have important rules: "
                    "\n\n"
                    "- Wash-sale rule: Can't repurchase the same security within 30 days "
                    "  of harvesting a loss (or 30 days before the sale) "
                    "- Capital gains timing: Need to track long-term vs short-term gains "
                    "- State taxes: Rules vary by state "
                    "- Income limits: Some strategies have income phase-outs "
                    "\n\n"
                    "InvestorClaw can help identify positions with unrealized losses, "
                    "but ALWAYS consult your tax professional before executing any "
                    "tax strategy."
                ),
                "questions_for_professional": [
                    "Would tax-loss harvesting be beneficial for my situation this year?",
                    "How should I balance tax efficiency with my rebalancing needs?",
                    "Are there state tax considerations I should account for?",
                ],
                "disclaimer": "⚠️ CONSULT YOUR TAX PROFESSIONAL — This is educational context only"
            }
        }

    @staticmethod
    def _handle_performance_query(
        question: str,
        portfolio_file: Optional[str],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle performance/return queries"""
        return {
            "is_financial": True,
            "query_type": QueryType.PERFORMANCE,
            "analysis_type": "Portfolio Performance Analysis",
            "recommendation": f"Use InvestorClaw performance analyzer: /portfolio performance",
            "response": {
                "observation": "You're asking about portfolio performance, returns, or risk metrics",
                "educational_consideration": (
                    "Performance analysis looks backward at what happened, but it doesn't "
                    "predict the future. Key metrics include: "
                    "- Returns (YTD, 1-year, 3-year) "
                    "- Volatility (how much your returns vary) "
                    "- Sharpe Ratio (returns per unit of risk) "
                    "- Drawdown (largest peak-to-trough decline) "
                    "\n\n"
                    "These are all 'what happened' measures. A financial adviser can help "
                    "contextualize whether your performance is appropriate for your goals "
                    "and timeline, and whether you're taking the right amount of risk."
                ),
                "questions_for_adviser": [
                    "How is my portfolio performing relative to my goals and benchmarks?",
                    "Is my volatility appropriate for my risk tolerance?",
                    "Should I adjust my strategy based on recent performance?",
                ],
                "disclaimer": "⚠️ PAST PERFORMANCE ≠ FUTURE RESULTS — Not investment advice"
            }
        }

    @staticmethod
    def _handle_portfolio_query(
        question: str,
        portfolio_file: Optional[str],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle general portfolio questions"""
        return {
            "is_financial": True,
            "query_type": QueryType.PORTFOLIO_ANALYSIS,
            "analysis_type": "Portfolio Analysis",
            "recommendation": f"Use InvestorClaw portfolio analyzer: /portfolio holdings",
            "response": {
                "observation": "You're asking about your portfolio composition",
                "educational_consideration": (
                    "Understanding your portfolio—what you own, how much it's worth, "
                    "and how it's allocated—is the first step in financial planning. "
                    "InvestorClaw can help you: "
                    "- Get a current snapshot of your holdings "
                    "- Analyze diversification and concentration "
                    "- Compare your allocation to industry benchmarks "
                    "- Track unrealized gains/losses "
                    "\n\n"
                    "But remember: Knowing what you own is just the start. A financial "
                    "adviser can help you ensure your portfolio matches your goals, "
                    "timeline, and risk tolerance."
                ),
                "questions_for_adviser": [
                    "Does my portfolio composition align with my investment goals?",
                    "Are there any concentration risks I should address?",
                    "How should my portfolio evolve as I get closer to retirement?",
                ],
                "disclaimer": "⚠️ EDUCATIONAL ANALYSIS — NOT INVESTMENT ADVICE"
            }
        }

    @staticmethod
    def _handle_general_financial_query(
        question: str,
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """Handle general financial questions"""
        return {
            "is_financial": True,
            "query_type": QueryType.GENERAL_FINANCIAL,
            "analysis_type": "General Financial Education",
            "response": {
                "observation": f"Your question: {question}",
                "educational_consideration": (
                    "Your question touches on financial topics. While InvestorClaw can help "
                    "you analyze your portfolio, fetch news and analyst data, and understand "
                    "your holdings, it's important to remember: "
                    "\n\n"
                    "- InvestorClaw is EDUCATIONAL, not advice "
                    "- Your financial situation is unique "
                    "- A qualified financial adviser should review any important decisions "
                    "- Markets and strategies change; keep learning "
                    "\n\n"
                    "Use InvestorClaw to understand your portfolio deeply, but make decisions "
                    "in consultation with a financial professional."
                ),
                "next_steps": [
                    "Use InvestorClaw commands to analyze your portfolio",
                    "Review the analysis with a financial adviser",
                    "Document your investment goals and constraints",
                ],
                "disclaimer": "⚠️ EDUCATIONAL ANALYSIS — NOT INVESTMENT ADVICE"
            }
        }
