pragma solidity ^0.8.0;
contract LoopsFixture { function sum(uint256 n) external pure returns (uint256 total) { for (uint256 i; i < n; ++i) total += i; } }
