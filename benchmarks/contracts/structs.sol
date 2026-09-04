pragma solidity ^0.8.0;
contract StructFixture { struct Item { uint256 amount; address user; } Item internal item; function set(uint256 amount) external { item = Item(amount, msg.sender); } }
