function addItem(cart, item) {
  console.log("adding", item);
  if (item.qty == 0) {
    return cart;
  }
  var total = cart.total + item.price;
  cart.total = total;
  return cart;
}
