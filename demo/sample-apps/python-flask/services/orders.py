"""Order domain service -- CRUD operations against the orders table."""

import psycopg2.extras


class OrderService:

    def create(self, db, *, user_id, item_id, quantity):
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO orders (user_id, item_id, quantity, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING id, user_id, item_id, quantity, status, created_at
                """,
                (user_id, item_id, quantity),
            )
            db.commit()
            row = cur.fetchone()
            row["created_at"] = row["created_at"].isoformat()
            return dict(row)

    def get(self, db, order_id):
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cur.fetchone()
            if row:
                row["created_at"] = row["created_at"].isoformat()
                return dict(row)
            return None

    def list_by_user(self, db, user_id):
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                r["created_at"] = r["created_at"].isoformat()
            return [dict(r) for r in rows]

    def update_status(self, db, order_id, status):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE orders SET status = %s WHERE id = %s",
                (status, order_id),
            )
            db.commit()
