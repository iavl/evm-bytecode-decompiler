pragma solidity ^0.8.0;
contract Solidity08Fixture { uint256 public value; error Invalid(); function set(uint256 next) external { if (next == 0) revert Invalid(); value = next; } }
