# --------------------------------------------------------------------------------
# 휴면 송도 고객 알림톡 발송 실행 (Flask 앱 컨텍스트 필요)
# - dry-run: 발송 없이 대상만 확인
# - 실행: python scripts/run_reengagement_alimtalk.py [--dry-run] [--weeks=2] [--limit=100]
# --------------------------------------------------------------------------------
import os
import sys
import argparse

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    parser = argparse.ArgumentParser(description="휴면 송도 고객에게 할인 쿠폰 알림톡 발송")
    parser.add_argument("--dry-run", action="store_true", help="실제 발송 없이 대상만 출력")
    parser.add_argument("--weeks", type=int, default=2, help="몇 주간 미주문 시 휴면으로 볼지 (기본 2)")
    parser.add_argument("--limit", type=int, default=100, help="최대 발송 인원 (기본 100)")
    parser.add_argument("--coupon", type=str, default="WELCOME2WEEKS", help="쿠폰 코드")
    args = parser.parse_args()

    from app import app
    from utils import (
        get_inactive_songdo_customers,
        run_reengagement_alimtalk,
        get_roas_metrics,
        get_roas_with_revenue,
        get_daangn_conversion_metrics,
    )

    with app.app_context():
        if args.dry_run:
            customers = get_inactive_songdo_customers(weeks=args.weeks, limit=args.limit)
            print(f"[dry-run] 송도 휴면 고객 {len(customers)}명 (최근 {args.weeks}주간 미주문)")
            for c in customers[:20]:
                print(f"  - {c['customer_name']} {c['customer_phone']} (마지막 주문: {c['last_order_at']})")
            if len(customers) > 20:
                print(f"  ... 외 {len(customers) - 20}명")
            return

        result = run_reengagement_alimtalk(
            weeks=args.weeks,
            dry_run=False,
            limit=args.limit,
            coupon_code=args.coupon,
        )
        print(f"발송: {result.get('sent', 0)}건, 실패: {result.get('failed', 0)}건")

        # ROAS 요약 (최근 30일 기준)
        metrics = get_roas_metrics(days_since=30)
        print(f"[ROAS] 최근 30일 발송 {metrics.get('sent_total', 0)}건, 재방문 주문 {metrics.get('revisit_orders', 0)}건, 재방문율 {metrics.get('revisit_rate', 0):.2%}")
        rev = get_roas_with_revenue(days_since=30)
        if rev.get("ad_spend"):
            print(f"[ROAS 매출] 광고비 {rev.get('ad_spend', 0):,}원, 재방문 매출 {rev.get('revisit_revenue', 0):,}원, ROAS {rev.get('roas', 0):.1f}배")
        daangn = get_daangn_conversion_metrics(days_since=30)
        if daangn.get("visits"):
            print(f"[당근 유입] 방문 {daangn.get('visits')}건, 결제 {daangn.get('orders_paid')}건, 전환율 {daangn.get('conversion_rate', 0):.1%}, 매출 {daangn.get('revenue', 0):,}원")


if __name__ == "__main__":
    main()
