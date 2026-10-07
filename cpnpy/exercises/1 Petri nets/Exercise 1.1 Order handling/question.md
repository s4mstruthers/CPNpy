# Exercise 1.1 — Order handling

A web shop handles each order as follows.

1. The order is received (**receive**).
2. Then the order is paid (**pay**) and shipped (**ship**). The shop does not
   wait for one before starting the other: both orders, and both at the same
   time, are possible.
3. When both are done, the order is closed (**close**).

Draw a **WF-net** that models this process. Use exactly the transition labels
in bold. Make sure your net is **sound**.

*Hint:* the net starts with one token in its source place $i$ and should end
with one token in its sink place $o$.

Press **Check** to compare your net with the model answer. It compares
behaviour, not drawings, so your layout and place names do not matter.
