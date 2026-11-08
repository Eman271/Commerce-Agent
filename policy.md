# Store Policy Document: Saira Fashion House (sample business)

This document is the single source of truth for delivery, payment, exchange and support rules. Prices, stock and order data are NOT stored here; they come from the catalog database.

## 1. Business Information

- Business name: Saira Fashion House (fictional store used for this project).
- Sells ready-to-wear and unstitched clothing, footwear and accessories for men, women and kids through WhatsApp, Instagram and website chat.
- Based in Gujranwala, Punjab, Pakistan. Online only; there is no walk-in showroom.
- The AI assistant replies 24/7. Human staff are available daily from 10:00 AM to 8:00 PM (Pakistan time). Escalated chats raised outside these hours are answered the next morning.

## 2. Delivery Areas and Charges

- We deliver all over Pakistan through courier partners.
- Delivery charges depend on the city:
  - Lahore, Gujranwala, Sialkot, Sheikhupura, Faisalabad, Islamabad, Rawalpindi: Rs. 250
  - Karachi, Peshawar, Multan, Quetta and all other cities or towns: Rs. 350
- Free delivery on orders with a product total of Rs. 10,000 or more (delivery charges are not counted in this amount).
- Delivery charges are added once per order, not per item.
- Estimated delivery time: 2 to 4 working days for the cities listed at Rs. 250, and 4 to 6 working days for all other areas.
- Delivery to addresses outside Pakistan is not available.

## 3. Payment (COD)

- Cash on Delivery (COD) is available in all delivery areas.
- The customer pays the total amount (product total plus delivery charges) in cash to the courier on receiving the parcel.
- COD orders with a total above Rs. 25,000 need advance payment confirmation by a human staff member. The AI must hand these over and must not confirm them.
- Online payment (bank transfer, JazzCash, Easypaisa) is handled by human staff only. The AI does not collect or verify payments.

## 4. Placing an Order

- To place an order the AI needs: product, color, size, quantity, customer name, phone number and full delivery address (including city).
- The AI must show an order summary (items, quantities, product total, delivery charges, grand total, payment method) and wait for the customer's clear confirmation (for example "yes", "haan", "confirm") before creating the order.
- Maximum quantity: 10 pieces of one item per order. Larger orders are handled by a human staff member.
- When an order is confirmed, the stock is reserved for that customer. If the customer does not confirm within 15 minutes, the reservation is released.
- Only items shown as in stock can be ordered. If an item is out of stock, the AI may suggest other colors or sizes of the same product.
- Changing or cancelling a confirmed order is handled by human staff. The AI hands over such requests.

## 5. Order Status

- Order statuses: Placed, Packed, Shipped, Delivered.
- Placed: order received. Packed: order is prepared at our store, usually within 24 hours. Shipped: handed over to the courier, the tracking number is available. Delivered: customer has received the parcel.
- To protect customer privacy, the AI shares order status only when the customer gives both the order number and the phone number used on the order. If they do not match, the AI must not share any order details.

## 6. Exchange Policy

The AI can create an exchange request automatically only when ALL of the following conditions are true:

1. The exchange request is made within 7 days of the delivery date.
2. The item was NOT bought on sale (items marked as sale are final sale and cannot be exchanged).
3. The item is unused, unwashed, and has its original tags and packaging.
4. The customer wants a different size or color of the same product (not a different product).
5. The requested size or color is in stock.
6. The item category allows exchange (see exclusions below).

Exclusions: the following categories are never exchangeable, even when not on sale: Modest wear (hijabs and abayas), Accessories (belts, bags) and Women Accessories (dupattas), and all unstitched fabric (men and women). Footwear can be exchanged only if unworn.

Exchange costs: the customer pays Rs. 250 courier charges for the exchange parcel. The replacement is sent only after we receive the original item.

If any condition is not met (late request, sale item, product in different condition, out-of-stock replacement), the AI must not decide on its own and must hand the case over to human staff with the order details.

## 7. Returns and Refunds

- The AI never approves, promises or processes refunds, returns for money, or compensation.
- Every refund or return request is escalated to a human staff member.
- If a customer receives a damaged, torn, wrong or defective item, they must send clear photos within 48 hours of delivery. The AI collects the order number and photos if possible and escalates the case. The AI does not decide whether the claim is valid.
- Refunds, if approved by a human, are processed within 7 to 10 working days.

## 8. Cases the AI Must Hand Over to a Human

The AI must escalate to human staff when:

- The customer asks for a refund, return, compensation or reports a damaged, wrong or defective item.
- The customer wants to cancel or change a confirmed order.
- The customer wants a discount, special price, bulk deal, or bargaining.
- The customer is angry, uses abusive language, mentions a complaint, consumer court or a legal action.
- The customer asks for a human ("insan se baat karni hai", "owner se baat karao").
- The request is unclear after two clarification attempts.
- The question is outside this policy or the AI is not sure of the answer. The AI must not guess.
- The action fails a business rule (for example quantity above the limit, COD above Rs. 25,000, order not found).

When handing over, the AI tells the customer that a staff member will reply during working hours, and sends the owner a summary: customer, order number (if any), issue, and the reason for escalation.

## 9. General Rules for the AI Assistant

- Use only information from the catalog database and this policy. Never invent prices, stock, delivery times or policies.
- If the customer writes in Roman Urdu, reply in simple Roman Urdu or the customer's language mix. Keep replies short and polite.
- Do not share any customer's personal information with another customer.
- Do not promise delivery dates; only give the estimated ranges in this document.
- Offers, discounts and sale prices are shown only as they appear in the catalog.

## 10. Frequently Asked Questions (Roman Urdu / English)

**Delivery kitne din mein hogi? (How many days does delivery take?)**
Lahore, Gujranwala, Sialkot, Sheikhupura, Faisalabad, Islamabad and Rawalpindi: 2 to 4 working days. Other cities: 4 to 6 working days.

**COD available hai? (Is COD available?)**
Yes, COD is available in all delivery areas. For orders above Rs. 25,000 a staff member will confirm the payment first.

**Delivery charges kitne hain? (What are the delivery charges?)**
Rs. 250 for major cities, Rs. 350 for other areas. Delivery is free on orders of Rs. 10,000 or more.

**Exchange ho sakta hai? (Can I exchange?)**
Yes, within 7 days of delivery for non-sale items that are unused with tags, for a different size or color. Sale items cannot be exchanged.

**Sale wale item exchange ho sakta hai? (Can sale items be exchanged?)**
No. Sale items are final sale and cannot be exchanged.

**Refund milega? (Will I get a refund?)**
Refund requests are reviewed by our staff. The AI assistant will pass your request to them.

**Mera order kahan hai? (Where is my order?)**
Please share your order number and the phone number used on the order, and the assistant will check the status.
