pragma solidity ^0.8.0;
contract EventsFixture { event Changed(address indexed who, uint256 value); uint256 public value; function set(uint256 next) external { value = next; emit Changed(msg.sender, next); } }
